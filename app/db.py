"""SQLite storage for ReBrand. Schema is portable to PostgreSQL later."""
import os
import sqlite3
import time

DB_PATH = os.environ.get("REBRAND_DB", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "rebrand.db"))

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS workspaces (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL CHECK(role IN ('creator','manager','reviewer')),
  pass_hash TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS blueprint_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
  version INTEGER NOT NULL,
  note TEXT DEFAULT '',
  created_by INTEGER REFERENCES users(id),
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS guidelines (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version_id INTEGER NOT NULL REFERENCES blueprint_versions(id),
  title TEXT NOT NULL,
  body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS terms (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version_id INTEGER NOT NULL REFERENCES blueprint_versions(id),
  term TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('banned','preferred')),
  replacement TEXT DEFAULT '',
  note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS claims (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version_id INTEGER NOT NULL REFERENCES blueprint_versions(id),
  claim TEXT NOT NULL,
  risk TEXT NOT NULL DEFAULT 'medium' CHECK(risk IN ('high','medium','low')),
  expires_on TEXT DEFAULT NULL
);
CREATE TABLE IF NOT EXISTS palette_colors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version_id INTEGER NOT NULL REFERENCES blueprint_versions(id),
  hex TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
  name TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  path TEXT NOT NULL,
  palette_json TEXT DEFAULT '[]',
  active INTEGER NOT NULL DEFAULT 1,
  uploaded_by INTEGER REFERENCES users(id),
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS submissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
  creator_id INTEGER NOT NULL REFERENCES users(id),
  title TEXT NOT NULL,
  content_type TEXT NOT NULL CHECK(content_type IN ('text','image','document')),
  channel TEXT DEFAULT 'web',
  text TEXT DEFAULT '',
  alt_text TEXT DEFAULT '',
  file_path TEXT DEFAULT '',
  state TEXT NOT NULL DEFAULT 'Draft'
    CHECK(state IN ('Draft','In Review','Approved','Published','Monitoring','In Recovery','Closed')),
  version_id INTEGER REFERENCES blueprint_versions(id),
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  checked_fingerprint TEXT DEFAULT '',
  approved_fingerprint TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS issues (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  submission_id INTEGER NOT NULL REFERENCES submissions(id),
  rule_code TEXT NOT NULL,
  category TEXT NOT NULL,
  severity TEXT NOT NULL CHECK(severity IN ('high','medium','low')),
  status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','accepted','disputed','resolved')),
  evidence TEXT NOT NULL,
  clause TEXT NOT NULL,
  suggestion TEXT DEFAULT '',
  source TEXT NOT NULL DEFAULT 'rule' CHECK(source IN ('rule','ai')),
  uncertain INTEGER NOT NULL DEFAULT 0,
  dispute_reason TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  submission_id INTEGER NOT NULL REFERENCES submissions(id),
  user_id INTEGER NOT NULL REFERENCES users(id),
  action TEXT NOT NULL CHECK(action IN ('approve','request_changes','reject')),
  reason TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS comments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  submission_id INTEGER NOT NULL REFERENCES submissions(id),
  user_id INTEGER NOT NULL REFERENCES users(id),
  body TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'comment',
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS published (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  submission_id INTEGER NOT NULL REFERENCES submissions(id),
  workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
  title TEXT NOT NULL,
  url TEXT DEFAULT '',
  version_id INTEGER NOT NULL REFERENCES blueprint_versions(id),
  approver_id INTEGER NOT NULL REFERENCES users(id),
  published_at REAL NOT NULL,
  state TEXT NOT NULL DEFAULT 'Monitoring' CHECK(state IN ('Monitoring','In Recovery','Closed'))
);
CREATE TABLE IF NOT EXISTS published_links (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  published_id INTEGER NOT NULL REFERENCES published(id),
  ref_type TEXT NOT NULL CHECK(ref_type IN ('guideline','claim','term','asset')),
  ref_key TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recovery_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  published_id INTEGER NOT NULL REFERENCES published(id),
  workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
  reason TEXT NOT NULL,
  triage TEXT NOT NULL DEFAULT 'medium' CHECK(triage IN ('high','medium','low')),
  owner_id INTEGER REFERENCES users(id),
  deadline TEXT DEFAULT '',
  action TEXT DEFAULT '',
  action_approved_by INTEGER REFERENCES users(id),
  state TEXT NOT NULL DEFAULT 'open'
    CHECK(state IN ('open','action_proposed','in_progress','recheck','closed')),
  detected_at REAL NOT NULL,
  corrected_at REAL,
  correction_note TEXT DEFAULT '',
  correction_confirmed_by INTEGER REFERENCES users(id),
  closed_at REAL
);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id INTEGER NOT NULL,
  user_id INTEGER,
  kind TEXT NOT NULL,
  message TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id INTEGER NOT NULL,
  actor_id INTEGER,
  action TEXT NOT NULL,
  entity TEXT NOT NULL,
  entity_id INTEGER,
  detail TEXT DEFAULT '',
  created_at REAL NOT NULL
);
"""


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init():
    conn = connect()
    journal = os.environ.get("REBRAND_JOURNAL", "").upper()
    if journal in ("DELETE", "TRUNCATE", "WAL"):
        # Apply the requested journal mode BEFORE the schema script (which says WAL);
        # WAL is unsafe on network volumes, so never enter it when overridden.
        conn.execute("PRAGMA journal_mode=" + journal)
        conn.executescript(SCHEMA.replace("PRAGMA journal_mode=WAL;", ""))
    else:
        conn.executescript(SCHEMA)
    # Upgrade databases created by earlier Round 2 builds without deleting demo data.
    for table, column, declaration in [
        ("submissions", "checked_fingerprint", "TEXT DEFAULT ''"),
        ("submissions", "approved_fingerprint", "TEXT DEFAULT ''"),
        ("recovery_tasks", "correction_note", "TEXT DEFAULT ''"),
        ("recovery_tasks", "correction_confirmed_by", "INTEGER"),
        ("sessions", "revoked_at", "REAL"),
    ]:
        present = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in present:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
    conn.commit()
    return conn


def now():
    return time.time()


def audit(conn, workspace_id, actor_id, action, entity, entity_id, detail=""):
    conn.execute(
        "INSERT INTO events (workspace_id, actor_id, action, entity, entity_id, detail, created_at) VALUES (?,?,?,?,?,?,?)",
        (workspace_id, actor_id, action, entity, entity_id, detail, now()),
    )


def current_version(conn, workspace_id):
    row = conn.execute(
        "SELECT * FROM blueprint_versions WHERE workspace_id=? ORDER BY version DESC LIMIT 1",
        (workspace_id,),
    ).fetchone()
    return row


def load_blueprint(conn, version_id):
    """Load a full blueprint snapshot for a version."""
    return {
        "version_id": version_id,
        "guidelines": [dict(r) for r in conn.execute("SELECT * FROM guidelines WHERE version_id=?", (version_id,))],
        "terms": [dict(r) for r in conn.execute("SELECT * FROM terms WHERE version_id=?", (version_id,))],
        "claims": [dict(r) for r in conn.execute("SELECT * FROM claims WHERE version_id=?", (version_id,))],
        "palette": [r["hex"] for r in conn.execute("SELECT hex FROM palette_colors WHERE version_id=?", (version_id,))],
    }
