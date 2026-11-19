import csv
import io
import re
import streamlit as st
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


PAGES = ['Dashboard', 'Test Case Generator', 'Historical RCA (coming soon)',
         'Defect & CR Board', 'Execution by FDR']
with st.sidebar:
    st.header('Navigation')
    page = st.selectbox('Select service', PAGES)
    st.caption('Jira: not connected · CSV fallback available · No Jira writes')
    with st.expander('Data Sources · CSV Uploads', expanded=False):
        st.caption('Upload exports from Jira/Xray or other systems. Imports are session-only; no live Jira sync is performed.')
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
        st.caption('Phase 1 POC · Local drafts · No Jira writes')
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
main, chat = st.columns([4, 1.35], gap='medium', vertical_alignment='top')

with main:
    if page == 'Dashboard':
        total = len(st.session_state.suite.test_cases) if st.session_state.suite else 0
        synced = sum(1 for row in st.session_state.jira_sync if row.get('sync_status', '').lower() == 'synced')
        with st.container(key='dashboard_summary'):
            st.markdown('##### Quality Overview')
            first = st.columns(2, gap='small')
            first[0].metric('Generated test cases', total)
            first[1].metric('Jira synced cases (import)', synced if st.session_state.jira_sync else '—')
            second = st.columns(2, gap='small')
            second[0].metric('Total defects (import)', metric_count('defects'))
            second[1].metric('Total CRs (import)', metric_count('changes'))
        st.caption('— means no snapshot uploaded. Imported counts are not live Jira data; generated cases are session drafts.')
        st.divider()
        a, b = st.columns(2)
        with a:
            with st.container(key='dashboard_defects'):
                st.markdown('#### Defect status')
                counts = status_counts(st.session_state.defects)
                if counts:
                    for status, count in sorted(counts.items()):
                        st.metric(status.title(), count)
                else:
                    st.caption('No defect data connected')
        with b:
            with st.container(key='dashboard_crs'):
                st.markdown('#### CR status')
                counts = status_counts(st.session_state.changes)
                if counts:
                    for status, count in sorted(counts.items()):
                        st.metric(status.title(), count)
                else:
                    st.caption('No change request data connected')
        with st.container(key='dashboard_fdr'):
            st.markdown('#### Execution summary by FDR')
            if st.session_state.executions:
                fdrs = sorted({r['fdr'] for r in st.session_state.executions})
                chosen = st.selectbox('Filter FDR', ['All FDRs'] + fdrs)
                rows = [r for r in st.session_state.executions if chosen == 'All FDRs' or r['fdr'] == chosen]
                grouped = {}
                for r in rows:
                    fdr = r['fdr']
                    status = r['status'].strip().upper().replace(' ', '_')
                    if fdr not in grouped:
                        grouped[fdr] = {'FDR': fdr, 'Total': 0, 'PASS': 0,
                                        'FAIL': 0, 'BLOCKED': 0, 'NOT RUN': 0}
                    grouped[fdr]['Total'] += 1
                    field = 'NOT RUN' if status in ('NOT_RUN', 'NOTRUN') else status
                    if field in ('PASS', 'FAIL', 'BLOCKED', 'NOT RUN'):
                        grouped[fdr][field] += 1
                st.dataframe(list(grouped.values()), hide_index=True, use_container_width=True)
            else:
                st.caption('No FDR execution data connected')
        with st.container(key='dashboard_latest'):
            st.markdown('#### Latest generated test cases')
            if st.session_state.suite is None:
                st.caption('No test cases generated yet')
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
            if st.session_state.executions:
                fdrs = sorted({r['fdr'] for r in st.session_state.executions})
                chosen = st.selectbox('FDR', fdrs)
                st.dataframe([r for r in st.session_state.executions if r['fdr'] == chosen],
                             hide_index=True, use_container_width=True)
            else:
                st.caption('No execution data connected. Upload CSV in the sidebar.')
    else:
        with st.container(key='rca_board'):
            st.markdown('#### Historical RCA')
            st.caption('Historical RCA integration is planned for a later phase.')

with chat:
    with st.container(key='assistant_card'):
      with st.expander('🤖 AI Assistant', expanded=False):
          st.caption('Answers based on current session data; no live Jira access')
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
              if re.search(r'\b(generat\w*|creat\w*|draft\w*)\b', lower) and re.search(r'\btest\s*cases?\b|\btestcases?\b', lower):
                  match = re.search(r'\b(\d{1,2})\s+test\s*cases?\b', lower)
                  count = min(15, max(1, int(match.group(1)))) if match else 5
                  requirement = re.sub(r'^.*?\btest\s*cases?\b\s*(?:for|from|based on|covering)?\s*',
                                       '', prompt, count=1, flags=re.I).strip(' :.-')
                  if len(requirement) < 20:
                      requirement = st.session_state.requirement
                  try:
                      suite, check = run_generation(requirement, count)
                      reply = f'Generated **{len(suite.test_cases)}** draft test cases. Guardrail: **{check["status"]}**. Human review required.'
                  except Exception as exc:
                      reply = f'Generation failed: {exc}'
              elif re.search(r'\b(defects?|bugs?)\b', lower):
                  counts = status_counts(st.session_state.defects)
                  reply = ('**Defects:** ' + str(len(st.session_state.defects)) + '\n\n' +
                           '\n'.join(f'- {k}: {v}' for k, v in counts.items())) if counts else 'No defect snapshot uploaded.'
              elif re.search(r'\b(crs?|change requests?)\b', lower):
                  counts = status_counts(st.session_state.changes)
                  reply = ('**CRs:** ' + str(len(st.session_state.changes)) + '\n\n' +
                           '\n'.join(f'- {k}: {v}' for k, v in counts.items())) if counts else 'No CR snapshot uploaded.'
              elif re.search(r'\b(executions?|fdr|pass|fail)\b', lower):
                  counts = status_counts(st.session_state.executions)
                  reply = ('**Execution records:** ' + str(len(st.session_state.executions)) + '\n\n' +
                           '\n'.join(f'- {k}: {v}' for k, v in counts.items())) if counts else 'No execution snapshot uploaded.'
              elif re.search(r'\b(jira|sync)\b', lower):
                  synced = sum(1 for r in st.session_state.jira_sync if r.get('sync_status', '').lower() == 'synced')
                  reply = f'**Imported Jira sync records marked Synced:** {synced}. Live Jira connection: **Not connected**.'
              elif re.search(r'\b(guardrail|validation|finding)\b', lower):
                  reply = (f'Guardrail source: **{st.session_state.guardrails_source}**. '
                           f'Status: **{check["status"] if check else "Not run"}**. '
                           + ('\n'.join(check.get('findings', [])) if check else ''))
              elif re.search(r'\b(requirement)\b', lower):
                  reply = st.session_state.requirement
              elif re.search(r'\b(cases?|testcases?|test cases?)\b', lower):
                  reply = f'**{total}** draft test cases generated in this session.'
              elif re.search(r'\b(dashboard|summary|overview|status)\b', lower):
                  reply = (f'**Dashboard:** {total} generated cases; {len(st.session_state.defects)} imported defects; '
                           f'{len(st.session_state.changes)} imported CRs; '
                           f'{len(st.session_state.executions)} imported executions. '
                           'Live Jira connection: not connected.')
              else:
                  reply = 'I can summarize generated test cases, imported defects, CRs, FDR executions, guardrails and Jira sync snapshots.'
              st.session_state.messages.append({'role': 'assistant', 'content': reply})
              st.rerun()