import json
import re
import streamlit as st
from dotenv import load_dotenv
from services.generator import generate_testcases

load_dotenv()
st.set_page_config(page_title='IMS AI Quality Board', page_icon='🐞', layout='wide')
st.title('🐞 IMS AI Quality Board')
st.caption('Phase 1 POC · Local test-case drafts · No Jira writes')

if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'suite' not in st.session_state:
    st.session_state.suite = None
if 'validation' not in st.session_state:
    st.session_state.validation = None
if 'requirement' not in st.session_state:
    st.session_state.requirement = 'An IMS subscriber shall register using SIP REGISTER. Successful authentication returns SIP 200 OK. Invalid credentials shall be rejected.'

with st.sidebar:
    st.header('Navigation')
    page = st.selectbox('Select service', ['Dashboard', 'Requirements', 'Test Case Generator', 'Historical RCA (coming soon)', 'Bug / CR Board (coming soon)', 'Execution (coming soon)'])
    st.info('Jira remains read-only. Generated cases are local drafts.')

main, chat = st.columns([1.8, 1], gap='large')

def show_suite():
    suite = st.session_state.suite
    if suite is None:
        return
    check = st.session_state.validation
    st.write('Guardrail status:', check['status'])
    for finding in check['findings']:
        st.warning(finding)
    st.caption('Human review required. Structural PASS does not prove telecom correctness.')
    for tc in suite.test_cases:
        with st.expander(f'{tc.id} · {tc.title} ({tc.category})'):
            st.write('Preconditions:', '; '.join(tc.preconditions) or 'None specified')
            st.table([{'Step': i, 'Action': step.action, 'Expected result': step.expected_result} for i, step in enumerate(tc.steps, 1)])
    st.download_button('Download draft JSON', suite.model_dump_json(indent=2), file_name='testcases_draft.json', mime='application/json')

def run_generation(requirement, count):
    with st.spinner('Generating and validating test cases...'):
        suite, validation = generate_testcases(requirement, count)
    st.session_state.suite = suite
    st.session_state.validation = validation
    return suite, validation

with main:
    if page == 'Dashboard':
        st.subheader('Dashboard')
        a, b, c = st.columns(3)
        a.metric('Generated draft cases', len(st.session_state.suite.test_cases) if st.session_state.suite else 0)
        b.metric('Guardrail status', st.session_state.validation['status'] if st.session_state.validation else 'Not run')
        c.metric('Jira sync', 'Not connected')
        st.info('Live FDR, defect, and CR metrics will appear after read-only Jira synchronization is implemented.')
        show_suite()
    elif page in ('Requirements', 'Test Case Generator'):
        st.subheader('Requirement → Test cases')
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
        show_suite()
    else:
        st.subheader(page)
        st.info('This module is planned for a later phase.')

with chat:
    st.subheader('🤖 AI Assistant')
    st.caption('Available: test-case generation. Other capabilities will be added later.')
    history = st.container(height=480)
    with history:
        for message in st.session_state.messages:
            with st.chat_message(message['role']):
                st.markdown(message['content'])
    prompt = st.chat_input('e.g. Generate 5 test cases for IMS registration...')
    if prompt:
        st.session_state.messages.append({'role': 'user', 'content': prompt})
        with history:
            with st.chat_message('user'):
                st.markdown(prompt)
        if re.search(r'\b(generat\w*|creat\w*|draft\w*)\b', prompt, re.I) and re.search(r'\btest\s*cases?\b|\btestcases?\b', prompt, re.I):
            count_match = re.search(r'\b(\d{1,2})\s+test\s*cases?\b', prompt, re.I)
            count = int(count_match.group(1)) if count_match else 5
            requirement = re.sub(r'^.*?\btest\s*cases?\b\s*(?:for|from|based on|covering)?\s*', '', prompt, count=1, flags=re.I).strip(' :.-')
            if len(requirement) < 20:
                requirement = st.session_state.requirement
            try:
                suite, check = run_generation(requirement, count)
                reply = f'Generated **{len(suite.test_cases)} draft test cases**. Guardrails: **{check["status"]}**. Review the cases in the Dashboard or Test Case Generator page. Human approval is required.'
                if check['findings']:
                    reply += '\n\n' + '\n'.join(f'- {f}' for f in check['findings'])
            except Exception as exc:
                reply = f'Unable to generate test cases: {exc}'
        else:
            reply = 'Currently I can generate test cases. Try: **Generate 5 test cases for IMS registration with valid and invalid credentials.** Jira queries and RCA will be added in later phases.'
        st.session_state.messages.append({'role': 'assistant', 'content': reply})
        with history:
            with st.chat_message('assistant'):
                st.markdown(reply)