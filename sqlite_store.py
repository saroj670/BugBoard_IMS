"""SQLite persistence for a small single-user Jira demonstration."""
import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(os.getenv('BUGBOARD_DB_PATH', str(Path(__file__).resolve().parent / 'bugboard_demo.db')))


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH), timeout=20)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=20000')
    db.execute('PRAGMA journal_mode=WAL')
    return db


def init_db():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS jira_issues (
            project TEXT NOT NULL,
            issue_key TEXT NOT NULL,
            fdr TEXT NOT NULL,
            record_type TEXT NOT NULL,
            status TEXT NOT NULL,
            updated TEXT,
            payload TEXT NOT NULL,
            PRIMARY KEY (project, issue_key)
        );
        CREATE INDEX IF NOT EXISTS idx_jira_fdr ON jira_issues(project, fdr);
        CREATE TABLE IF NOT EXISTS sync_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL,
            project_name TEXT,
            synced_at TEXT NOT NULL,
            issue_count INTEGER NOT NULL,
            snapshot_json TEXT NOT NULL
        );
        ''')


def save_snapshot(snapshot):
    init_db()
    project = snapshot['project']
    rows = snapshot.get('records', [])
    with connect() as db:
        db.execute('DELETE FROM jira_issues WHERE project = ?', (project,))
        db.executemany('''INSERT INTO jira_issues
            (project, issue_key, fdr, record_type, status, updated, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?)''', [
            (project, r['Key'], r.get('FDR', 'Unassigned'), r.get('Record Type', 'Other'),
             r.get('Status', 'Unknown'), r.get('Updated', ''), json.dumps(r))
            for r in rows
        ])
        db.execute('''INSERT INTO sync_history(project, project_name, synced_at, issue_count, snapshot_json)
                      VALUES (?, ?, ?, ?, ?)''',
                   (project, snapshot.get('project_name', project), snapshot['synced_at'],
                    len(rows), json.dumps(snapshot)))


def latest_snapshot(project='DJ'):
    init_db()
    with connect() as db:
        row = db.execute('''SELECT snapshot_json FROM sync_history
                            WHERE project = ? ORDER BY id DESC LIMIT 1''', (project.upper(),)).fetchone()
    return json.loads(row['snapshot_json']) if row else None


def records(project='DJ', fdr='All FDRs'):
    init_db()
    with connect() as db:
        if fdr == 'All FDRs':
            rows = db.execute('SELECT payload FROM jira_issues WHERE project=? ORDER BY issue_key', (project.upper(),)).fetchall()
        else:
            rows = db.execute('SELECT payload FROM jira_issues WHERE project=? AND fdr=? ORDER BY issue_key', (project.upper(), fdr)).fetchall()
    return [json.loads(row['payload']) for row in rows]


def fdrs(project='DJ'):
    init_db()
    with connect() as db:
        rows = db.execute("SELECT DISTINCT fdr FROM jira_issues WHERE project=? AND fdr != 'Unassigned' ORDER BY fdr", (project.upper(),)).fetchall()
    return [r['fdr'] for r in rows]


def metrics(project='DJ', fdr='All FDRs'):
    data = records(project, fdr)
    kinds = ['Test Case', 'Test Set', 'Test Plan', 'Test Execution', 'Defect']
    result = {kind: sum(r.get('Record Type') == kind for r in data) for kind in kinds}
    result['Total Issues'] = len(data)
    result['FDRs'] = len({r.get('FDR') for r in data if r.get('FDR') not in ('Unassigned', None, '')})
    return result


def history(project='DJ', limit=100):
    init_db()
    with connect() as db:
        rows = db.execute('SELECT synced_at, issue_count FROM sync_history WHERE project=? ORDER BY id DESC LIMIT ?', (project.upper(), limit)).fetchall()
    return [dict(row) for row in rows]