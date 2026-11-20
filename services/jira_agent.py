"""Read-only Jira Cloud REST client. Uses personal API token with Basic auth.

Required environment: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN.
No issue modifications are performed.
"""
import os
import re
from urllib.parse import urlparse

import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv


class JiraError(RuntimeError):
    pass


def setting(name, default=''):
    value = os.getenv(name, '')
    if not value:
        try:
            import streamlit as st
            value = st.secrets.get(name, '')
        except Exception:
            pass
    return str(value or default).strip()


class JiraAgent:
    def __init__(self):
        load_dotenv()
        self.base_url = setting('JIRA_BASE_URL', 'https://sarojtripathy275.atlassian.net').rstrip('/')
        email = setting('JIRA_EMAIL')
        token = setting('JIRA_API_TOKEN')
        parsed = urlparse(self.base_url)
        if parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.atlassian.net') or parsed.path:
            raise JiraError('JIRA_BASE_URL must be an HTTPS Atlassian site URL without a path.')
        if not email or not token:
            raise JiraError('Set JIRA_EMAIL and JIRA_API_TOKEN in .env or Streamlit secrets.')
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(email, token)
        self.session.headers.update({'Accept': 'application/json'})

    def get(self, path, params=None):
        try:
            response = self.session.get(self.base_url + '/rest/api/3' + path,
                                        params=params, timeout=35)
        except requests.RequestException as exc:
            raise JiraError(f'Cannot connect to Jira: {type(exc).__name__}') from exc
        if not response.ok:
            details = {401: 'Authentication failed: check personal Jira email and token.',
                       403: 'Access denied: check project permissions and token scopes.',
                       404: 'Project or endpoint not found on this Jira site.'}.get(response.status_code, 'Jira request failed.')
            raise JiraError(f'HTTP {response.status_code}: {details}')
        try:
            return response.json()
        except ValueError as exc:
            raise JiraError('Jira returned invalid JSON.') from exc

    def project(self, key):
        if not re.fullmatch(r'[A-Z][A-Z0-9_]{1,19}', key):
            raise JiraError('Invalid project key.')
        return self.get('/project/' + key)

    def issues(self, key):
        """Retrieve every issue using Jira Cloud enhanced JQL search pagination."""
        self.project(key)  # distinguish wrong site/project from an empty result
        issues = {}
        next_token = None
        seen = set()
        for _ in range(100):
            params = {
                'jql': f'project = "{key}" ORDER BY created DESC',
                'maxResults': 100,
                'fields': 'summary,status,issuetype,labels,priority,updated,created',
            }
            if next_token:
                params['nextPageToken'] = next_token
            data = self.get('/search/jql', params=params)
            for issue in data.get('issues', []):
                if issue.get('key'):
                    issues[issue['key']] = issue
            new_token = data.get('nextPageToken')
            if not new_token:
                return list(issues.values())
            if new_token in seen:
                raise JiraError('Jira repeated its pagination token; sync aborted.')
            seen.add(new_token)
            next_token = new_token
        raise JiraError('More than 100 pages returned; sync aborted.')