"""Read-only Jira REST synchronization for the DJ BugBoard POC.

Snapshots are stored locally for a single-user demo. Streamlit Cloud disk is ephemeral.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from services.jira_agent import JiraAgent
from sqlite_store import save_snapshot, latest_snapshot

SNAPSHOT = Path(__file__).resolve().parent / 'jira_snapshot.json'


def normalise(issue, base_url):
    fields = issue.get('fields') or {}
    labels = [str(x).strip() for x in (fields.get('labels') or [])]
    lower = {x.lower() for x in labels}
    summary = str(fields.get('summary') or '')
    issue_type = str((fields.get('issuetype') or {}).get('name') or '')
    name = issue_type.lower()
    if name == 'bug' or 'record-defect' in lower:
        kind = 'Defect'
    elif name == 'test execution' or 'record-execution' in lower:
        kind = 'Test Execution'
    elif name == 'test plan' or 'record-testplan' in lower:
        kind = 'Test Plan'
    elif name == 'test set' or 'record-testset' in lower:
        kind = 'Test Set'
    elif name == 'test' or 'record-testcase' in lower:
        kind = 'Test Case'
    elif 'record-fdr' in lower:
        kind = 'FDR'
    else:
        kind = 'Other'
    fdr = next((x.upper() for x in labels if re.fullmatch(r'FDR-[A-Z0-9-]+', x, re.I)), None)
    if not fdr:
        match = re.search(r'\bFDR-[A-Z0-9-]+\b', summary, re.I)
        fdr = match.group(0).upper() if match else 'Unassigned'
    key = str(issue.get('key') or '')
    return {
        'Key': key, 'Summary': summary, 'Record Type': kind,
        'Issue Type': issue_type, 'FDR': fdr,
        'Status': str((fields.get('status') or {}).get('name') or 'Unknown'),
        'Priority': str((fields.get('priority') or {}).get('name') or ''),
        'Updated': str(fields.get('updated') or ''),
        'Labels': ', '.join(labels), 'URL': base_url + '/browse/' + key,
    }


def sync_project(project='DJ'):
    project = project.strip().upper()
    if not re.fullmatch(r'[A-Z][A-Z0-9_]{1,19}', project):
        raise ValueError('Invalid Jira project key')
    client = JiraAgent()
    project_info = client.project(project)
    records = [normalise(issue, client.base_url) for issue in client.issues(project)]
    snapshot = {
        'project': project, 'project_name': project_info.get('name', project),
        'synced_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'source': 'Jira Cloud REST API (read-only)', 'records': records,
    }
    temp = SNAPSHOT.with_suffix('.tmp')
    temp.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding='utf-8')
    temp.replace(SNAPSHOT)
    save_snapshot(snapshot)
    return snapshot


def load_snapshot(project='DJ'):
    stored = latest_snapshot(project)
    if stored is not None:
        return stored
    if not SNAPSHOT.exists():
        return None
    try:
        snapshot = json.loads(SNAPSHOT.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return None
    return snapshot if snapshot.get('project') == project.strip().upper() else None


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', default='DJ')
    args = parser.parse_args()
    try:
        data = sync_project(args.project)
        print(f"SYNC SUCCESS: {len(data['records'])} issues in {data['project']} ({data['project_name']})")
    except Exception as exc:
        print(f'SYNC FAILED: {exc}')
        raise SystemExit(1)