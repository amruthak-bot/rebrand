"""Demo story loader. Fresh seeded db, server on :8000."""
import sys
sys.path.insert(0, "tests")
from test_e2e import call
cr = call("POST", "/api/login", body={"email": "creator@demo.test", "password": "creator123"})["token"]
mg = call("POST", "/api/login", body={"email": "manager@demo.test", "password": "manager123"})["token"]
call("POST", "/api/demo/load", token=cr, expect=403)
call("POST", "/api/demo/load", token=mg)
call("POST", "/api/demo/load", token=mg, expect=409)
pub = call("GET", "/api/published", token=mg)
assert len(pub) == 3, pub
rec = [t for t in call("GET", "/api/recovery", token=mg) if t["state"] != "closed"]
assert len(rec) == 1
ex = call("GET", "/api/claims/expiry?days=30", token=mg)["claims"]
assert any(c["status"] == "expiring_soon" and c["live_posts_using_it"] for c in ex)
sg = call("GET", "/api/guideline-suggestions", token=mg)["suggestions"]
assert sg and sg[0]["times_disputed"] == 2
sc1 = call("POST", "/api/claims/expiry/scan", token=mg)
sc2 = call("POST", "/api/claims/expiry/scan", token=mg)
assert sc2["notices"] == [], "scan must not repeat the same notice on the same day"
print("DEMO STORY: ALL CHECKS PASSED")

# AI tone endpoint (browser-side Puter output is untrusted)
sid = call("POST", "/api/submissions", token=cr, body={"title": "T", "channel": "social", "text": "Hello everyone, we are thrilled to announce things."})["id"]
call("POST", f"/api/submissions/{sid}/check", token=cr)
r = call("POST", f"/api/submissions/{sid}/ai-tone", token=cr, body={"items": [
    {"clause": "We write plainly and confidently", "evidence": "we are thrilled to announce", "suggestion": "Say it plainly."},
    {"clause": "made up rule", "evidence": "thrilled", "suggestion": "x"},
    {"clause": "x", "evidence": "words that are not in the draft", "suggestion": "y"}]})
assert r["kept"] == 2 and r["dropped_not_quoted_from_draft"] == 1, r
ai = [i for i in r["issues"] if i["source"] == "ai" and i["status"] == "open"]
assert len(ai) == 2 and sorted(i["uncertain"] for i in ai) == [0, 1], ai
assert all(i["severity"] == "medium" for i in ai)
print("AI TONE ENDPOINT: PASSED")
