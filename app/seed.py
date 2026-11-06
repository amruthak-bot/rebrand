"""Seed a demo workspace with users and a sample brand blueprint.
Demo logins (local demo only):
  creator@demo.test / creator123   (Creator)
  manager@demo.test / manager123   (Manager)
  reviewer@demo.test / reviewer123 (Reviewer / brand manager)
"""
from . import db, security

DEMO_GUIDELINES = [
    {"title": "Voice and tone", "body": "We write plainly and confidently. We do not exaggerate. "
     "We avoid hype words and superlatives unless the claim is in the approved claim library. "
     "We use inclusive language: say 'everyone' or 'team', never 'guys'. Sentences stay short."},
    {"title": "Claims and evidence", "body": "Every promotional claim must come from the approved claim library. "
     "Claims with an expiry date must not be used after that date. Never invent statistics."},
    {"title": "Visual identity", "body": "Use only current approved assets. Dominant colours in published images "
     "should come from the approved brand palette. Every image needs descriptive alt text."},
    {"title": "Accessibility", "body": "All published images need alt text. Long written content uses headings "
     "without skipping levels. Public content should read at about grade 12 or below."},
]

DEMO_TERMS = [
    {"term": "guys", "kind": "banned", "replacement": "everyone", "note": "Inclusive language"},
    {"term": "utilise", "kind": "preferred", "replacement": "use", "note": "Plain language"},
    {"term": "synergy", "kind": "banned", "replacement": "cooperation", "note": "No jargon"},
]

DEMO_CLAIMS = [
    {"claim": "Rated 4.8/5 by 2,000+ customers", "risk": "high", "expires_on": None},
    {"claim": "Used by teams in 12 countries", "risk": "medium", "expires_on": None},
    {"claim": "Winter offer: 20% off until January", "risk": "high", "expires_on": "2026-01-31"},
]

DEMO_PALETTE = ["#1a56db", "#0e2145", "#ffffff", "#f5f7fb"]


def run():
    conn = db.init()
    if conn.execute("SELECT count(*) AS n FROM users").fetchone()["n"]:
        print("Already seeded.")
        return
    ws = conn.execute("INSERT INTO workspaces (name, created_at) VALUES (?,?)",
                      ("Demo Org", db.now())).lastrowid
    users = {}
    for email, name, role, pw in [
        ("creator@demo.test", "Demo Creator", "creator", "creator123"),
        ("manager@demo.test", "Demo Manager", "manager", "manager123"),
        ("reviewer@demo.test", "Demo Reviewer", "reviewer", "reviewer123"),
    ]:
        uid = conn.execute(
            "INSERT INTO users (workspace_id, name, email, role, pass_hash, created_at) VALUES (?,?,?,?,?,?)",
            (ws, name, email, role, security.hash_password(pw), db.now())).lastrowid
        users[role] = uid
    vid = conn.execute(
        "INSERT INTO blueprint_versions (workspace_id, version, note, created_by, created_at) VALUES (?,?,?,?,?)",
        (ws, 1, "Initial demo blueprint", users["reviewer"], db.now())).lastrowid
    for g in DEMO_GUIDELINES:
        conn.execute("INSERT INTO guidelines (version_id, title, body) VALUES (?,?,?)", (vid, g["title"], g["body"]))
    for t in DEMO_TERMS:
        conn.execute("INSERT INTO terms (version_id, term, kind, replacement, note) VALUES (?,?,?,?,?)",
                     (vid, t["term"], t["kind"], t["replacement"], t["note"]))
    for c in DEMO_CLAIMS:
        conn.execute("INSERT INTO claims (version_id, claim, risk, expires_on) VALUES (?,?,?,?)",
                     (vid, c["claim"], c["risk"], c["expires_on"]))
    for hexv in DEMO_PALETTE:
        conn.execute("INSERT INTO palette_colors (version_id, hex) VALUES (?,?)", (vid, hexv))
    db.audit(conn, ws, users["reviewer"], "workspace.seeded", "workspace", ws, "Demo workspace")
    conn.commit()
    print(f"Seeded workspace {ws} with 3 users and blueprint v1.")


if __name__ == "__main__":
    run()
