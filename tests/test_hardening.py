"""Judge-abuse hardening: empty content, double actions, auth. Fresh seeded db, server on REBRAND_BASE."""
import sys
sys.path.insert(0, "tests")
from test_e2e import call

def main():
    cr = call("POST", "/api/login", body={"email": "creator@demo.test", "password": "creator123"})["token"]
    mg = call("POST", "/api/login", body={"email": "manager@demo.test", "password": "manager123"})["token"]
    # empty post cannot pass review
    se = call("POST", "/api/submissions", body={"title": "", "content_type": "text", "channel": "web", "text": ""}, token=cr)["id"]
    r = call("POST", f"/api/submissions/{se}/check", token=cr)
    codes = [i["rule_code"] for i in r["issues"]]
    assert "EMPTY_CONTENT" in codes, codes
    assert any(i["rule_code"]=="EMPTY_CONTENT" and i["severity"]=="high" for i in r["issues"])
    call("POST", f"/api/submissions/{se}/decision", body={"action":"approve","reason":"ok"}, token=mg, expect=400)
    print("PASS empty content flagged high and approval blocked")
    # double approve / double publish rejected
    s2 = call("POST", "/api/submissions", body={"title": "h", "content_type": "text", "channel": "web", "text": "Our winter collection launches today."}, token=cr)["id"]
    call("POST", f"/api/submissions/{s2}/check", token=cr)
    call("POST", f"/api/submissions/{s2}/decision", body={"action":"approve","reason":"ok"}, token=mg)
    call("POST", f"/api/submissions/{s2}/decision", body={"action":"approve","reason":"ok"}, token=mg, expect=400)
    call("POST", f"/api/submissions/{s2}/publish", body={"url":"https://example.test/h"}, token=mg)
    call("POST", f"/api/submissions/{s2}/publish", body={"url":"https://example.test/h"}, token=mg, expect=400)
    print("PASS double approve and double publish rejected")
    # auth walls
    call("GET", "/api/submissions", token=None, expect=401)
    call("POST", "/api/login", body={"email":"creator@demo.test","password":"wrong"}, expect=401)
    print("PASS unauthenticated requests and bad login rejected")
    # huge text accepted without a crash, still checked
    s3 = call("POST", "/api/submissions", body={"title": "big", "content_type": "text", "channel": "web", "text": "A "*100000}, token=cr)["id"]
    r = call("POST", f"/api/submissions/{s3}/check", token=cr)
    assert r["state"] == "In Review", r
    print("PASS 200KB post checked without a crash")

if __name__ == "__main__":
    main()
