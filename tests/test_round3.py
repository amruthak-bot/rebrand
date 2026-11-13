"""Round 3 features against a live server on :8000 with a FRESH seeded db.
Run: python -m app.seed; python run.py; python tests/test_round3.py
(Do not run in the same db as test_e2e.py.)"""
import datetime, sys
sys.path.insert(0, "tests")
from test_e2e import call

def main():
    cr = call("POST", "/api/login", body={"email": "creator@demo.test", "password": "creator123"})["token"]
    mg = call("POST", "/api/login", body={"email": "manager@demo.test", "password": "manager123"})["token"]
    soon = (datetime.date.today() + datetime.timedelta(days=10)).isoformat()
    # blueprint with a claim expiring soon
    bp = call("GET", "/api/blueprint/current", token=mg)
    claims = [{"claim": c["claim"], "risk": c["risk"], "expires_on": c["expires_on"]} for c in bp["claims"]]
    claims.append({"claim": "Spring sale ends soon", "risk": "low", "expires_on": soon})
    base = {"note": "add soon-expiring claim",
            "guidelines": [{"title": g["title"], "body": g["body"]} for g in bp["guidelines"]],
            "terms": [{"term": t["term"], "kind": t["kind"], "replacement": t["replacement"], "note": t["note"]} for t in bp["terms"]],
            "claims": claims, "palette": bp["palette"]}
    call("POST", "/api/blueprint/preview", token=mg, body=base)
    call("POST", "/api/blueprint", token=mg, body=base)
    # publish a post using that claim
    s = call("POST", "/api/submissions", token=cr, body={"title": "Spring", "content_type": "text", "channel": "social",
             "text": "Hello everyone! Spring sale ends soon. We use cooperation to win."})["id"]
    r = call("POST", f"/api/submissions/{s}/check", token=cr)
    call("POST", f"/api/submissions/{s}/decision", token=mg, body={"action": "approve"})
    call("POST", f"/api/submissions/{s}/publish", token=cr, body={"url": "https://example.test/spring"})

    # 1. IMPACT PREVIEW: banning a word used in the live post
    prev_body = dict(base, terms=base["terms"] + [{"term": "cooperation", "kind": "banned", "replacement": "teamwork", "note": "x"}])
    pv = call("POST", "/api/blueprint/preview", token=mg, body=prev_body)
    assert pv["newly_failing_posts"] == 1 and pv["saved"] is False, pv
    assert pv["causes"][0]["rule_code"] == "TERM_BANNED"
    assert call("GET", "/api/blueprint/current", token=mg)["version"] == 2  # nothing saved
    call("POST", "/api/blueprint/preview", token=cr, body=prev_body, expect=403)
    assert not [t for t in call("GET", "/api/recovery", token=mg) if t["state"] != "closed"]
    pv0 = call("POST", "/api/blueprint/preview", token=mg, body=base)
    assert pv0["newly_failing_posts"] == 0

    # 2. CLAIM EXPIRY: soon-expiring claim detected, owner notified, renewal by human
    ex = call("GET", "/api/claims/expiry?days=30", token=mg)
    st = {c["claim"]: c["status"] for c in ex["claims"]}
    assert st["Spring sale ends soon"] == "expiring_soon", st
    assert st["Winter offer: 20% off until January"] == "expired"
    call("POST", "/api/claims/expiry/scan", token=cr, expect=403)
    sc = call("POST", "/api/claims/expiry/scan", token=mg)
    assert any(n["claim"] == "Spring sale ends soon" for n in sc["notices"]), sc
    assert call("GET", "/api/notifications", token=mg)
    call("POST", "/api/claims/renew", token=mg, body={"claim": "Spring sale ends soon", "new_expires_on": "2027-03-01", "evidence_note": ""}, expect=400)
    call("POST", "/api/claims/renew", token=cr, body={"claim": "x", "new_expires_on": "2027-03-01", "evidence_note": "y"}, expect=403)
    call("POST", "/api/claims/renew", token=mg, body={"claim": "Spring sale ends soon", "new_expires_on": "2027-03-01", "evidence_note": "Campaign extended per marketing lead"})
    ex2 = call("GET", "/api/claims/expiry?days=30", token=mg)
    assert {c["claim"]: c["status"] for c in ex2["claims"]}["Spring sale ends soon"] == "current"

    # expired claim in an already-live post opens recovery
    # 3. DISPUTE LEARNING
    s2 = call("POST", "/api/submissions", token=cr, body={"title": "D", "content_type": "text", "channel": "social",
              "text": "Hey guys, welcome. Hey guys again."})["id"]
    iss = call("POST", f"/api/submissions/{s2}/check", token=cr)["issues"]
    for i in iss[:2]:
        call("POST", f"/api/issues/{i['id']}/dispute", token=cr, body={"reason": "casual greeting used in our community voice"})
    sg = call("GET", "/api/guideline-suggestions", token=mg)["suggestions"]
    assert sg and sg[0]["confidence"] == "strong" and "draft" in sg[0]["status"], sg
    v = call("GET", "/api/blueprint/current", token=mg)["version"]
    call("POST", "/api/guideline-suggestions/approve", token=cr, body={"rule_code": "TERM_BANNED", "wording": "x"}, expect=403)
    call("POST", "/api/guideline-suggestions/approve", token=mg, body={"rule_code": sg[0]["rule_code"], "wording": sg[0]["proposed_wording"]})
    bp2 = call("GET", "/api/blueprint/current", token=mg)
    assert bp2["version"] > v and any(g["title"].startswith("Clarification") for g in bp2["guidelines"])
    print("ROUND 3: ALL CHECKS PASSED")

main()
