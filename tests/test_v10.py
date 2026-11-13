"""v10 regression suite: one check per 360-degree pass fix. Fresh seeded db, server on REBRAND_BASE.
Covers: decision state gate, dispute-on-resolved, empty report reason, security headers,
login throttle, text caps, bad content_type, health version."""
import os
import sys
import urllib.request
sys.path.insert(0, "tests")
from test_e2e import call
BASE = os.environ.get("REBRAND_BASE", "http://127.0.0.1:8000")


def main():
    cr = call("POST", "/api/login", body={"email": "creator@demo.test", "password": "creator123"})["token"]
    mg = call("POST", "/api/login", body={"email": "manager@demo.test", "password": "manager123"})["token"]

    # 1. security headers on every response
    req = urllib.request.Request(BASE + "/api/health")
    with urllib.request.urlopen(req) as r:
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"
        body = r.read().decode()
    assert '"version":"0.10.0"' in body, body
    print("PASS security headers + health version")

    # 2. bad content_type rejected
    call("POST", "/api/submissions", token=cr,
         body={"title": "x", "content_type": "hologram", "text": "hi"}, expect=400)
    print("PASS bad content_type rejected 400")

    # 3. text caps
    call("POST", "/api/submissions", token=cr,
         body={"title": "x" * 301, "text": "hi"}, expect=400)
    call("POST", "/api/submissions", token=cr,
         body={"title": "big", "text": "y" * 500001}, expect=400)
    print("PASS oversized title/text rejected 400")

    # 4. decision state gate: request_changes on a Published item must not flip it back to Draft
    sid = call("POST", "/api/submissions", token=cr,
               body={"title": "Gate post", "text": "Hello everyone! A clean post."})["id"]
    call("POST", f"/api/submissions/{sid}/check", token=cr)
    call("POST", f"/api/submissions/{sid}/decision", token=mg, body={"action": "approve"})
    call("POST", f"/api/submissions/{sid}/publish", token=cr, body={"url": "https://example.test/gate"})
    call("POST", f"/api/submissions/{sid}/decision", token=mg,
         body={"action": "request_changes", "reason": "late change"}, expect=400)
    state = call("GET", f"/api/submissions/{sid}", token=mg)["state"]
    assert state == "Published", state
    print("PASS request_changes on Published refused; register intact")

    # 5. dispute on a resolved issue refused
    sid2 = call("POST", "/api/submissions", token=cr,
                body={"title": "Dispute post", "text": "Hey guys, this is bad."})["id"]
    r = call("POST", f"/api/submissions/{sid2}/check", token=cr)
    iss = [i for i in r["issues"] if i["rule_code"] == "TERM_BANNED"][0]
    call("POST", f"/api/issues/{iss['id']}/accept", token=cr)
    call("PATCH", f"/api/submissions/{sid2}", token=cr, body={"text": "Hello everyone, this is fine."})
    call("POST", f"/api/submissions/{sid2}/check", token=cr)  # old issue now resolved
    call("POST", f"/api/issues/{iss['id']}/dispute", token=cr, body={"reason": "late dispute"}, expect=400)
    print("PASS dispute on resolved issue refused 400")

    # 6. empty report reason refused
    pid = call("GET", "/api/published", token=mg)[0]["id"]
    call("POST", f"/api/published/{pid}/report", token=cr, body={"reason": "   "}, expect=400)
    print("PASS empty report reason refused 400")

    # 7. empty comment refused
    call("POST", f"/api/submissions/{sid2}/comments", token=cr, body={"body": "  "}, expect=400)
    print("PASS empty comment refused 400")

    # 8. login throttle: 8 bad tries -> 429
    for _ in range(8):
        call("POST", "/api/login", body={"email": "throttle@demo.test", "password": "nope"}, expect=401)
    call("POST", "/api/login", body={"email": "throttle@demo.test", "password": "nope"}, expect=429)
    print("PASS login throttle 429 after repeated failures")

    print("ALL v10 CHECKS PASSED")


if __name__ == "__main__":
    main()
