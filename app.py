import csv
import io
import re
import streamlit as st
import pandas as pd
from jira_sync import sync_project, load_snapshot
from sqlite_store import latest_snapshot, history as db_history, init_db
from dotenv import load_dotenv
from services.generator import generate_testcases, load_default_guardrails, parse_guardrails, suite_to_csv

load_dotenv()
st.set_page_config(page_title='AI Quality Board', page_icon='🐞', layout='wide', initial_sidebar_state='collapsed')

DEFAULT_REQUIREMENT = ('An IMS subscriber shall register using SIP REGISTER. Successful authentication '
                       'returns SIP 200 OK. Invalid credentials shall be rejected.')
for key, default in {
    'messages': [], 'suite': None, 'validation': None, 'requirement': DEFAULT_REQUIREMENT,
    'guardrails_text': load_default_guardrails(), 'guardrails_source': 'Default file',
    'defects': [], 'changes': [], 'executions': [], 'jira_sync': [],
    'live_snapshot': None, 'jira_error': None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

DATASETS = {
    'defects': ('Defect ID', ['defect_id', 'status', 'fdr'], 'defect_id,status,fdr,priority\nBUG-001,Open,FDR-IMS-01,High\n'),
    'changes': ('CR ID', ['cr_id', 'status', 'fdr'], 'cr_id,status,fdr\nCR-001,In Progress,FDR-IMS-01\n'),
    'executions': ('Execution ID', ['execution_id', 'test_case_id', 'status', 'fdr'], 'execution_id,test_case_id,status,fdr\nEX-001,TC-001,PASS,FDR-IMS-01\n'),
    'jira_sync': ('Jira Key', ['test_case_id', 'jira_key', 'sync_status'], 'test_case_id,jira_key,sync_status\nTC-001,DJ-101,Synced\n'),
}


def load_csv(uploaded, required):
    if uploaded is None:
        return None
    if uploaded.size > 2_000_000:
        raise ValueError('CSV must be 2 MB or smaller.')
    data = uploaded.getvalue().decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(data))
    if not reader.fieldnames or not set(required).issubset(set(reader.fieldnames)):
        raise ValueError('Required CSV columns: ' + ', '.join(required))
    rows = []
    for row in reader:
        if None in row:
            raise ValueError('CSV row has extra columns.')
        rows.append({key: (value or '').strip() for key, value in row.items()})
    if len(rows) > 10000:
        raise ValueError('CSV supports up to 10,000 records.')
    return rows


def status_counts(rows):
    result = {}
    for row in rows:
        status = (row.get('status') or 'Unknown').strip().upper()
        result[status] = result.get(status, 0) + 1
    return result


def metric_count(key):
    return len(st.session_state[key]) if st.session_state[key] else '—'


def show_suite():
    suite = st.session_state.suite
    if suite is None:
        return
    check = st.session_state.validation
    if check:
        st.write('Guardrail status:', check['status'])
        for finding in check.get('findings', []):
            st.warning(finding)
    st.caption('Human review required. Structural PASS does not prove telecom correctness.')
    for tc in suite.test_cases:
        with st.expander(f'{tc.id} · {tc.title} ({tc.category})'):
            st.write('Preconditions:', '; '.join(tc.preconditions) or 'None specified')
            st.table([{'Step': i, 'Action': step.action, 'Expected result': step.expected_result}
                      for i, step in enumerate(tc.steps, 1)])
    st.download_button('Download test cases CSV', suite_to_csv(suite, check).encode('utf-8-sig'),
                       file_name='ims_testcases_draft.csv', mime='text/csv')


def run_generation(requirement, count):
    with st.spinner('Generating and validating test cases...'):
        suite, validation = generate_testcases(requirement, count, st.session_state.guardrails_text)
    st.session_state.suite = suite
    st.session_state.validation = validation
    return suite, validation


PAGES = ['Dashboard', 'Test Case Generator', 'Historical RCA',
         'Defect & CR Board', 'Execution by FDR']
with st.sidebar:
    st.header('Navigation')
    page = st.selectbox('Select service', PAGES)
    st.caption('Jira REST: DJ project · read-only · CSV fallback available')
    project_key = st.text_input('Jira project key', value='DJ').strip().upper()
    if st.button('🔄 Sync Jira now', type='primary', use_container_width=True):
        with st.spinner(f'Reading Jira project {project_key}...'):
            try:
                st.session_state.live_snapshot = sync_project(project_key)
                st.session_state.jira_error = None
            except Exception as exc:
                st.session_state.jira_error = str(exc)
    if st.session_state.jira_error:
        st.error('Jira sync failed: ' + st.session_state.jira_error)
    st.caption('Jira credentials are loaded from .env locally or Streamlit secrets in the cloud.')
    with st.expander('Data Sources · CSV Uploads', expanded=False):
        st.caption('Optional CSV fallback; Jira sync uses the live REST API.')
        for key, (id_label, required, template) in DATASETS.items():
            st.download_button(f'Download {key} CSV template', template, f'{key}_template.csv',
                               mime='text/csv', key=f'template_{key}')
            uploaded = st.file_uploader(f'{key.replace("_", " ").title()} CSV', type=['csv'], key=f'upload_{key}')
            if uploaded is not None:
                try:
                    rows = load_csv(uploaded, required)
                    st.session_state[key] = rows
                    st.success(f'Loaded {len(rows)} {key} records')
                except (UnicodeError, ValueError, csv.Error) as exc:
                    st.error(f'{key}: {exc}')
        if st.button('Clear imported snapshots'):
            for key in DATASETS:
                st.session_state[key] = []
            st.rerun()

header_left, header_center = st.columns([3, 2], vertical_alignment='center')
with header_left:
    with st.container(key='brand_header'):
        st.markdown('#### 🐞 AI Quality Board')
        st.caption('Live Jira read-only dashboard · AI-generated drafts stay local')
with header_center:
    with st.container(key='page_header'):
        st.markdown(f"<h3 style='text-align:center'>{page}</h3>", unsafe_allow_html=True)


# Consistent blue-outlined cards across the application.
st.markdown("""
<style>
:root { --ims-blue:#4098ff; --ims-card:#30465e; }
.block-container { padding-top:3.8rem; padding-bottom:2rem; max-width:1500px; }
div[data-testid="stVerticalBlock"] { gap: .8rem; }
.st-key-brand_header,
.st-key-page_header,
.st-key-dashboard_summary,
.st-key-dashboard_summary [data-testid="stMetric"],
.st-key-dashboard_defects,
.st-key-dashboard_crs,
.st-key-dashboard_fdr,
.st-key-dashboard_latest,
.st-key-generator_setup,
.st-key-generator_results,
.st-key-defect_board,
.st-key-cr_board,
.st-key-execution_board,
.st-key-rca_board,
.st-key-assistant_card {
    border: 3pt solid var(--ims-blue) !important;
    border-radius: 12px !important;
    background: var(--ims-card) !important;
    padding: 10px 13px !important;
    box-shadow: 0 5px 18px rgba(0,0,0,.12);
}
.st-key-brand_header, .st-key-page_header { min-height: 75px; display:flex; justify-content:center; flex-direction:column; }
.st-key-brand_header *, .st-key-page_header * { color:#fff !important; }
/* Separate enclosing frame around the four KPI cards. */
.st-key-dashboard_summary {
    background: #14283e !important;
    padding: 15px !important;
    margin-top: 18px !important;
    margin-bottom: 12px !important;
}
.st-key-dashboard_summary [data-testid="stMetric"] { min-height: 83px; }
.st-key-dashboard_summary [data-testid="stMetric"] *,
.st-key-dashboard_defects *,
.st-key-dashboard_crs *,
.st-key-dashboard_fdr *,
.st-key-dashboard_latest *,
.st-key-generator_setup *,
.st-key-generator_results *,
.st-key-defect_board *,
.st-key-cr_board *,
.st-key-execution_board *,
.st-key-rca_board *,
.st-key-assistant_card * {
    color: #fff !important;
}
.st-key-dashboard_summary [data-testid="stMetricLabel"] p {
    font-weight: 650 !important;
}
.st-key-dashboard_defects [data-testid="stMetric"],
.st-key-dashboard_crs [data-testid="stMetric"] {
    border: 0 !important;
    padding: 0 !important;
    background: transparent !important;
}
.st-key-dashboard_defects h4, .st-key-dashboard_crs h4,
.st-key-dashboard_fdr h4 { margin-top: 0 !important; }
.st-key-dashboard_summary [data-testid="stMetricValue"] {
    font-size: 1.25rem !important;
}
.st-key-generator_setup [data-testid="stFileUploader"],
.st-key-generator_setup [data-testid="stForm"],
.st-key-assistant_card [data-testid="stChatMessage"] {
    border-radius: 9px;
}
/* Compact headings, labels and controls; avoid shrinking readable body text. */
.st-key-brand_header h4 { font-size:1.15rem !important; margin:0 !important; }
.st-key-brand_header [data-testid="stCaptionContainer"] { font-size:.72rem !important; }
.st-key-page_header h3 { font-size:1.15rem !important; margin:0 !important; }
.st-key-dashboard_summary [data-testid="stMetricLabel"] p { font-size:.77rem !important; }
.st-key-dashboard_defects h4, .st-key-dashboard_crs h4,
.st-key-dashboard_fdr h4, .st-key-dashboard_latest h4 { font-size:1rem !important; }
.st-key-assistant_card { padding:8px 10px !important; }
.st-key-assistant_card [data-testid="stExpander"] summary { font-size:.78rem !important; }
@media (max-width: 768px) {
  .st-key-dashboard_summary [data-testid="stMetric"] { min-height: 90px; }
}
</style>
""", unsafe_allow_html=True)
# Initialize SQLite once per rerun; keep local generator and CSV functionality intact.
try:
    init_db()
    db_error = None
except Exception as exc:
    db_error = str(exc)

snapshot = None
if not db_error:
    snapshot = latest_snapshot(project_key)
if snapshot is None:
    snapshot = st.session_state.live_snapshot or load_snapshot(project_key)
all_jira_records = snapshot.get('records', []) if snapshot else []
available_fdrs = sorted({r.get('FDR') for r in all_jira_records if r.get('FDR') not in ('', None, 'Unassigned')})

main, chat = st.columns([4, 1.35], gap='medium', vertical_alignment='top')
with main:
    if db_error:
        st.warning(f'SQLite unavailable: {db_error}. Showing available Jira snapshot instead.')
    if page == 'Dashboard':
        if snapshot:
            st.caption(f"Jira source: {snapshot['source']} | Project: {snapshot['project_name']} ({snapshot['project']}) | Last sync: {snapshot['synced_at']}")
            selected_fdr = st.selectbox('Filter by FDR', ['All FDRs'] + available_fdrs, key='dashboard_fdr_filter')
            visible = [r for r in all_jira_records if selected_fdr == 'All FDRs' or r.get('FDR') == selected_fdr]
            def count_kind(kind):
                return sum(r.get('Record Type') == kind for r in visible)
            with st.container(key='dashboard_summary'):
                st.markdown('##### Live Jira Quality Overview')
                metrics = [
                    ('FDRs', len({r['FDR'] for r in visible if r.get('FDR') not in ('', 'Unassigned')})),
                    ('Test Cases', count_kind('Test Case')),
                    ('Test Sets', count_kind('Test Set')),
                    ('Test Plans', count_kind('Test Plan')),
                    ('Executions', count_kind('Test Execution')),
                    ('Defects', count_kind('Defect')),
                    ('Total Issues', len(visible)),
                ]
                columns = st.columns(4)
                for index, (label, value) in enumerate(metrics):
                    columns[index % 4].metric(label, value)
            st.caption('Dashboard shows numbers only. See Execution by FDR for charts and Jira issue details.')
        else:
            st.info('Click **Sync Jira now** in the sidebar to load Jira records into SQLite. No demo counts are invented.')
        with st.expander('Locally generated test cases (not yet saved to Jira)'):
            if st.session_state.suite is None:
                st.caption('Use Test Case Generator to create local drafts.')
            else:
                show_suite()
    elif page == 'Test Case Generator':
        with st.container(key='generator_setup'):
            st.markdown('#### Generate and validate test cases')
            st.caption('Upload guardrails → enter requirement → generate → validate → download CSV')
            st.download_button('Download default guardrails.txt', load_default_guardrails(),
                               file_name='default_guardrails.txt', mime='text/plain')
            uploaded = st.file_uploader('Upload custom guardrails (.txt)', type=['txt'])
            if uploaded is not None:
                try:
                    content = uploaded.getvalue().decode('utf-8-sig')
                    parse_guardrails(content)
                    st.session_state.guardrails_text = content
                    st.session_state.guardrails_source = uploaded.name
                    st.success(f'Active guardrails: {uploaded.name}')
                except (UnicodeError, ValueError) as exc:
                    st.error(f'Invalid guardrail file: {exc}')
                    st.stop()
            else:
                st.session_state.guardrails_text = load_default_guardrails()
                st.session_state.guardrails_source = 'Default file'
            with st.expander('View active guardrail rules'):
                st.code(st.session_state.guardrails_text, language='text')
            with st.form('generation_form'):
                requirement = st.text_area('Requirement or acceptance criteria', value=st.session_state.requirement, height=160)
                count = st.number_input('Number of test cases', min_value=1, max_value=15, value=5)
                submitted = st.form_submit_button('Generate + validate')
            if submitted:
                st.session_state.requirement = requirement
                try:
                    run_generation(requirement, int(count))
                except Exception as exc:
                    st.error(f'Generation failed: {exc}')
        with st.container(key='generator_results'):
            st.markdown('#### Generated test cases')
            if st.session_state.suite is None:
                st.caption('Generated cases and CSV download will appear here')
            else:
                show_suite()
    elif page == 'Defect & CR Board':
        for label, key, card_key in [
            ('Defects', 'defects', 'defect_board'),
            ('Change Requests (CR)', 'changes', 'cr_board')
        ]:
            with st.container(key=card_key):
                st.markdown(f'#### {label}')
                if st.session_state[key]:
                    st.dataframe(st.session_state[key], hide_index=True, use_container_width=True)
                else:
                    st.caption(f'No {label.lower()} data connected. Upload CSV in the sidebar.')
    elif page == 'Execution by FDR':
        with st.container(key='execution_board'):
            st.markdown('#### Execution by FDR')
            if snapshot:
                default_fdr = st.session_state.get('dashboard_fdr_filter', 'All FDRs')
                choices = ['All FDRs'] + available_fdrs
                chosen = st.selectbox('FDR', choices, index=choices.index(default_fdr) if default_fdr in choices else 0, key='execution_fdr_filter')
                visible = [r for r in all_jira_records if chosen == 'All FDRs' or r.get('FDR') == chosen]
                executions = [r for r in visible if r.get('Record Type') == 'Test Execution']
                st.metric('Test Executions', len(executions))
                left, right = st.columns(2)
                with left:
                    st.markdown('##### Issue type distribution')
                    if visible:
                        st.bar_chart(pd.Series([r.get('Record Type', 'Other') for r in visible]).value_counts())
                    else:
                        st.info('No matching issues.')
                with right:
                    st.markdown('##### Jira workflow status')
                    if visible:
                        st.bar_chart(pd.Series([r.get('Status', 'Unknown') for r in visible]).value_counts())
                    else:
                        st.info('No matching issues.')
                st.markdown('##### Execution records')
                if executions:
                    st.dataframe(pd.DataFrame([{'FDR': r['FDR'], 'Issue': r['Key'],
                                                'Summary': r['Summary'], 'Jira Status': r['Status'],
                                                'Link': r['URL']} for r in executions]),
                                 column_config={'Link': st.column_config.LinkColumn('Open Jira')},
                                 hide_index=True, use_container_width=True)
                else:
                    st.info('No test execution issues for this FDR.')
                st.caption('Jira workflow status is not Xray step-level PASS/FAIL. No execution result is inferred.')
                st.markdown('##### All Jira issues for selected FDR')
                if visible:
                    table = pd.DataFrame(visible)
                    st.dataframe(table[['Key', 'Record Type', 'FDR', 'Summary', 'Status', 'Priority', 'URL']],
                                 column_config={'URL': st.column_config.LinkColumn('Open Jira')},
                                 hide_index=True, use_container_width=True)
                    st.download_button('Download Jira issues CSV', table.to_csv(index=False).encode('utf-8-sig'),
                                       file_name=f'{project_key.lower()}_fdr_issues.csv', mime='text/csv')
            elif st.session_state.executions:
                fdr_values = sorted({r['fdr'] for r in st.session_state.executions})
                chosen = st.selectbox('FDR', fdr_values)
                st.dataframe([r for r in st.session_state.executions if r['fdr'] == chosen],
                             hide_index=True, use_container_width=True)
            else:
                st.caption('No Jira execution data yet. Sync Jira in the sidebar or upload execution CSV.')
    else:
        with st.container(key='rca_board'):
            st.markdown('#### Historical RCA')
            st.caption('Phase 3: similar-defect search and evidence-based RCA are planned. SQLite history is available below.')
            if snapshot and not db_error:
                history_rows = db_history(project_key)
                if history_rows:
                    st.dataframe(pd.DataFrame(history_rows), hide_index=True, use_container_width=True)
                else:
                    st.info('No saved sync history yet.')
            else:
                st.info('Sync Jira to begin collecting local history.')

with chat:
    with st.container(key='assistant_card'):
      with st.expander('🤖 AI Assistant', expanded=False):
          st.caption('Answers from current session and last synced Jira snapshot; no Jira writes')
          history = st.container(height=260, border=False)
          with history:
              for message in st.session_state.messages:
                  with st.chat_message(message['role']):
                      st.markdown(message['content'])
          prompt = st.chat_input('Ask about dashboard or test cases...', key='assistant_prompt')
          if prompt:
              st.session_state.messages.append({'role': 'user', 'content': prompt})
              lower = prompt.lower()
              suite = st.session_state.suite
              check = st.session_state.validation
              total = len(suite.test_cases) if suite else 0
              match_fdr = re.search(r'\bFDR-[A-Z0-9-]+\b', prompt, re.I)
              selected_context = (st.session_state.get('execution_fdr_filter', 'All FDRs') if page == 'Execution by FDR' else st.session_state.get('dashboard_fdr_filter', 'All FDRs'))
              context = match_fdr.group(0).upper() if match_fdr else selected_context
              if context not in available_fdrs and context != 'All FDRs':
                  context_valid = False
              else:
                  context_valid = True
              relevant = [r for r in all_jira_records if context == 'All FDRs' or r.get('FDR') == context]
              def jira_count(kind):
                  return sum(r.get('Record Type') == kind for r in relevant)
              if re.search(r'\b(generat\w*|creat\w*|draft\w*)\b', lower) and re.search(r'\btest\s*cases?\b|\btestcases?\b', lower):
                  count_match = re.search(r'\b(\d{1,2})\s+test\s*cases?\b', lower)
                  count = min(15, max(1, int(count_match.group(1)))) if count_match else 5
                  requirement = re.sub(r'^.*?\btest\s*cases?\b\s*(?:for|from|based on|covering)?\s*', '', prompt, count=1, flags=re.I).strip(' :.-')
                  if len(requirement) < 20:
                      requirement = st.session_state.requirement
                  try:
                      generated_suite, validation = run_generation(requirement, count)
                      reply = f'Generated **{len(generated_suite.test_cases)}** draft test cases. Guardrail: **{validation["status"]}**. Human review required.'
                  except Exception as exc:
                      reply = f'Generation failed: {exc}'
              elif re.search(r'\b(guardrail|validation|finding)\b', lower):
                  reply = (f'Guardrail source: **{st.session_state.guardrails_source}**. '
                           f'Status: **{check["status"] if check else "Not run"}**. '
                           + ('\n'.join(check.get('findings', [])) if check else ''))
              elif re.search(r'\b(requirement)\b', lower):
                  reply = st.session_state.requirement
              elif re.search(r'\b(local|generated|draft)\b', lower) and re.search(r'\b(test\s*cases?|testcases?)\b', lower):
                  reply = f'**{total}** draft test cases generated in this session.'
              elif re.search(r'\b(crs?|change requests?)\b', lower):
                  counts = status_counts(st.session_state.changes)
                  reply = ('**Imported CRs:** ' + str(len(st.session_state.changes)) + '\n\n' +
                           '\n'.join(f'- {k}: {v}' for k, v in counts.items())) if counts else 'No change-request CSV uploaded; Jira CR classification is not synchronized.'
              elif not snapshot:
                  reply = 'No Jira data synchronized yet. Click **Sync Jira now** in the sidebar.'
              elif not context_valid:
                  reply = f'No synchronized Jira records found for **{context}**. Last sync: {snapshot["synced_at"]}.'
              elif re.search(r'\b(status|state|progress|workflow)\b', lower) and re.search(r'\b(test\s*cases?|testcases?|fdr|dj-\d+)\b', lower):
                  # Report Jira workflow states only; never interpret them as Xray PASS/FAIL.
                  issue_key_match = re.search(r'\b[A-Z][A-Z0-9_]+-\d+\b', prompt, re.I)
                  if issue_key_match:
                      issue_key = issue_key_match.group(0).upper()
                      candidates = [r for r in all_jira_records if r.get('Key', '').upper() == issue_key]
                      if candidates:
                          item = candidates[0]
                          reply = (f'**{item["Key"]} — Jira issue status**\n\n'
                                   f'- Summary: {item.get("Summary", "")}\n'
                                   f'- Issue type: {item.get("Record Type", "Other")}\n'
                                   f'- FDR: {item.get("FDR", "Unassigned")}\n'
                                   f'- Workflow status: **{item.get("Status", "Unknown")}**\n'
                                   f'- [Open in Jira]({item.get("URL", "")})\n\n'
                                   'This is the Jira workflow status, not an Xray test execution PASS/FAIL result.')
                      else:
                          reply = f'Issue **{issue_key}** was not found in the latest synchronized Jira snapshot.'
                  else:
                      cases = [r for r in relevant if r.get('Record Type') == 'Test Case']
                      execution_issues = [r for r in relevant if r.get('Record Type') == 'Test Execution']
                      distribution = status_counts([{'status': r.get('Status', 'Unknown')} for r in cases])
                      lines = [f'**Test case workflow status — {context}**',
                               f'Last synced: {snapshot["synced_at"]}', '',
                               f'**Test cases: {len(cases)}**', '']
                      if cases:
                          lines += ['| Jira key | Test case | Workflow status |', '|---|---|---|']
                          for r in cases[:30]:
                              safe_summary = str(r.get('Summary', '')).replace('|', '/').replace('\n', ' ')
                              lines.append(f'| [{r["Key"]}]({r["URL"]}) | {safe_summary} | **{r.get("Status", "Unknown")}** |')
                          if len(cases) > 30:
                              lines.append(f'\nShowing 30 of {len(cases)} cases.')
                          lines += ['', '**Workflow totals:** ' + ', '.join(f'{status}: {count}' for status, count in sorted(distribution.items()))]
                      else:
                          lines.append('No test case issues found for this FDR.')
                      lines += ['', f'**Test execution issues:** {len(execution_issues)}',
                                '**Actual PASS/FAIL:** Not available from the current Jira REST snapshot.',
                                'Jira Backlog/In Progress/Done is not a test execution result.']
                      reply = '\n'.join(lines)
              elif re.search(r'\b(rca|root cause|similar defects?|history|historical)\b', lower):
                  reply = 'Historical RCA analysis is planned for Phase 3. Current Jira records alone do not establish verified root causes.'
              elif re.search(r'\b(pass|fail|passed|failed|xray|step.level)\b', lower):
                  reply = ('The current Jira sync does not retrieve Xray step-level PASS/FAIL. '
                           'Jira issue workflow status is not an execution result. '
                           f'Found **{jira_count("Test Execution")}** execution issues for **{context}**.')
              elif re.search(r'\b(list|show|which|details?)\b', lower) and re.search(r'\b(defects?|bugs?|executions?|test\s*cases?|test\s*plans?|test\s*sets?)\b', lower):
                  kind = ('Defect' if re.search(r'\b(defects?|bugs?)\b', lower) else
                          'Test Execution' if re.search(r'\bexecutions?\b', lower) else
                          'Test Plan' if re.search(r'\btest\s*plans?\b', lower) else
                          'Test Set' if re.search(r'\btest\s*sets?\b', lower) else 'Test Case')
                  matches = [r for r in relevant if r.get('Record Type') == kind]
                  reply = (f'**{kind} issues for {context}: {len(matches)}**\n\n' +
                           '\n'.join(f'- [{r["Key"]}]({r["URL"]}): {r["Summary"]} ({r["Status"]})' for r in matches[:20])) if matches else f'No {kind.lower()} issues found for {context}.'
                  if len(matches) > 20:
                      reply += f'\n\nShowing 20 of {len(matches)}. See Execution by FDR for the full table.'
              else:
                  reply = (f'**Jira {context}** · last synced {snapshot["synced_at"]}\n\n'
                           f'- Test Cases: **{jira_count("Test Case")}**\n'
                           f'- Test Sets: **{jira_count("Test Set")}**\n'
                           f'- Test Plans: **{jira_count("Test Plan")}**\n'
                           f'- Executions: **{jira_count("Test Execution")}**\n'
                           f'- Defects: **{jira_count("Defect")}**\n'
                           f'- Total Issues: **{len(relevant)}**\n\n'
                           'Counts come from synchronized Jira records; no results are invented.')
              st.session_state.messages.append({'role': 'assistant', 'content': reply})
              st.rerun()