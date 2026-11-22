"""Read-only Jira Cloud REST client for BugBoard.

Authentication: Jira email + personal API token (HTTP Basic).
Cloud: Streamlit secrets take precedence over process environment.
Local: .env is supported. No Jira records are modified.
"""
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth


class JiraError(RuntimeError):
    pass


def setting(name, default=""):
    # Load local .env without overriding existing process environment.
    load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env", override=False)
    try:
        import streamlit as st
        # On Streamlit Cloud, explicitly configured secrets take priority.
        value = st.secrets.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    except (ImportError, FileNotFoundError, RuntimeError, KeyError):
        pass
    return str(os.getenv(name) or default).strip()


class JiraAgent:
    def __init__(self):
        self.base_url = setting("JIRA_BASE_URL").rstrip("/")
        email = setting("JIRA_EMAIL")
        token = setting("JIRA_API_TOKEN")
        parsed = urlparse(self.base_url)
        if (parsed.scheme != "https" or not parsed.hostname
                or not parsed.hostname.endswith(".atlassian.net")
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise JiraError("JIRA_BASE_URL must be the HTTPS Jira site root, without a path.")
        if not email or not token:
            raise JiraError("Missing JIRA_EMAIL or JIRA_API_TOKEN in Streamlit Secrets / .env.")
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(email, token)
        self.session.headers.update({"Accept": "application/json"})

    def get(self, path, params=None):
        if not path.startswith("/"):
            raise JiraError("Invalid Jira API path.")
        endpoint = "/rest/api/3" + path
        try:
            response = self.session.get(self.base_url + endpoint, params=params, timeout=35)
        except requests.RequestException as exc:
            raise JiraError(f"Cannot connect to Jira at {endpoint}: {type(exc).__name__}") from exc
        if not response.ok:
            detail = {
                401: "Authentication failed; verify personal Jira email and API token.",
                403: "Access denied; verify permissions and token type.",
                404: "Project inaccessible, wrong Jira site, or unsupported API endpoint.",
            }.get(response.status_code, "Jira request failed.")
            # Do not print the response body, query parameters, or credentials.
            raise JiraError(f"HTTP {response.status_code} on GET {endpoint}: {detail}")
        try:
            return response.json()
        except ValueError as exc:
            raise JiraError(f"Invalid JSON returned by GET {endpoint}.") from exc

    def project(self, key):
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,19}", key):
            raise JiraError("Invalid Jira project key.")
        return self.get("/project/" + key)

    def issues(self, key):
        self.project(key)
        issues = {}
        next_token = None
        seen = set()
        for _ in range(100):
            params = {
                "jql": f'project = "{key}" ORDER BY created DESC',
                "maxResults": 100,
                "fields": "summary,status,issuetype,labels,priority,updated,created",
            }
            if next_token:
                params["nextPageToken"] = next_token
            data = self.get("/search/jql", params=params)
            for issue in data.get("issues", []):
                if issue.get("key"):
                    issues[issue["key"]] = issue
            new_token = data.get("nextPageToken")
            if not new_token:
                return list(issues.values())
            if new_token in seen:
                raise JiraError("Jira repeated a pagination token; sync aborted.")
            seen.add(new_token)
            next_token = new_token
        raise JiraError("Jira returned more than 100 pages; sync aborted.")