"""Activity tab backend: audit trail is recorded, workspace-scoped, newest first.
Run against a live server with a FRESH seeded db: REBRAND_BASE=http://127.0.0.1:8000 python tests/test_activity.py"""
import sys
sys.path.insert(0, "tests")
from test_e2e import call

def main():
    cr = call("POST", "/api/login", body={"email": "creator@demo.test", "password": "creator123"})["token"]
    mg = call("POST", "/api/login", body={"email": "manager@demo.test", "password": "manager123"})["token"]
    sid = call("POST", "/api/submissions", body={"title": "Activity probe", "content_type": "text", "channel": "web", "text": "Our winter collection launches today with calm confidence"}, token=cr)["id"]
    call("POST", f"/api/submissions/{sid}/check", token=cr)
    call("POST", f"/api/submissions/{sid}/decision", body={"action": "approve", "reason": "probe"}, token=mg)
    rows = call("GET", "/api/audit", token=cr)
    assert isinstance(rows, list) and len(rows) >= 3, rows
    kinds = [r["action"] for r in rows]
    assert "submission.created" in kinds and "submission.checked" in kinds and "submission.approve" in kinds, kinds
    by_action = {r["action"]: r for r in rows}
    assert by_action["submission.created"]["actor"] == "Demo Creator", by_action["submission.created"]
    assert by_action["submission.approve"]["actor"] == "Demo Manager", by_action["submission.approve"]
    assert all(rows[i]["created_at"] >= rows[i+1]["created_at"] for i in range(len(rows)-1)), "not newest-first"
    assert "Activity probe" in (by_action["submission.created"]["detail"] or ""), by_action["submission.created"]
    print(f"PASS GET /api/audit :: {len(rows)} events, actors and order verified")

if __name__ == "__main__":
    main()
