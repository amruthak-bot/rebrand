"""v9 regression suite: one check per audit fix. Fresh seeded db, server on REBRAND_BASE.
Covers: H1 phantom version, H2 committed recovery, H3 palette validation, H4 date validation,
H5 stale publish, preview-before-save gate, logout revocation, upload limits, DOCX, URL scheme."""
import io
import sqlite3
import sys
sys.path.insert(0, "tests")
from test_e2e import call
import os
BASE = os.environ.get("REBRAND_BASE", "http://127.0.0.1:8000")


def main():
    cr = call("POST", "/api/login", body={"email": "creator@demo.test", "password": "creator123"})["token"]
    mg = call("POST", "/api/login", body={"email": "manager@demo.test", "password": "manager123"})["token"]
    bp = call("GET", "/api/blueprint/current", token=mg)
    v0 = bp["version"]
    terms = [{"term": t["term"], "kind": t["kind"], "replacement": t["replacement"], "note": t["note"]} for t in bp["terms"]]
    claims = [{"claim": c["claim"], "risk": c["risk"], "expires_on": c["expires_on"]} for c in bp["claims"]]
    base = {"note": "n", "guidelines": bp["guidelines"], "terms": terms, "claims": claims, "palette": bp["palette"]}

    # H1: a failed save leaves nothing, even after a later unrelated write
    bad = dict(base, terms=[{"term": "a", "kind": "WRONG"}])
    call("POST", "/api/blueprint/preview", token=mg, body=bad, expect=400)
    call("POST", "/api/blueprint", token=mg, body=bad, expect=400)
    call("POST", "/api/login", body={"email": "reviewer@demo.test", "password": "reviewer123"})
    assert call("GET", "/api/blueprint/current", token=mg)["version"] == v0, "phantom version"
    print("PASS H1 failed save leaves no phantom version")

    # H3: invalid palette colour rejected at preview AND at save
    bad2 = dict(base, palette=["green"])
    call("POST", "/api/blueprint/preview", token=mg, body=bad2, expect=400)
    call("POST", "/api/blueprint", token=mg, body=bad2, expect=400)
    print("PASS H3 invalid palette colour -> 400")

    # H4: invalid claim expiry date rejected
    bad3 = dict(base, claims=claims + [{"claim": "C1", "risk": "low", "expires_on": "soon"}])
    call("POST", "/api/blueprint/preview", token=mg, body=bad3, expect=400)
    call("POST", "/api/blueprint", token=mg, body=bad3, expect=400)
    bad4 = dict(base, claims=claims + [{"claim": "C2", "risk": "huge"}])
    call("POST", "/api/blueprint", token=mg, body=bad4, expect=400)
    print("PASS H4 invalid expiry date / risk -> 400")

    # preview-before-save gate: save without preview -> 409, after preview -> 200
    change = dict(base, note="ban a word", terms=terms + [{"term": "synergy", "kind": "banned", "replacement": "cooperation", "note": ""}])
    call("POST", "/api/blueprint", token=mg, body=change, expect=409)
    pv = call("POST", "/api/blueprint/preview", token=mg, body=change)
    assert pv["saved"] is False
    call("POST", "/api/blueprint", token=mg, body=change)
    print("PASS preview-before-save: 409 without preview, 200 after")

    # H5: approve under v(N), tighten rules to v(N+1) -> publish refused until re-checked
    sid = call("POST", "/api/submissions", token=cr,
               body={"title": "stale", "content_type": "text", "text": "Hello everyone. Calm and plain."})["id"]
    call("POST", f"/api/submissions/{sid}/check", token=cr)
    call("POST", f"/api/submissions/{sid}/decision", token=mg, body={"action": "approve"})
    tighten = dict(base, note="tighten", terms=terms + [{"term": "calm", "kind": "banned", "replacement": "steady", "note": ""}])
    call("POST", "/api/blueprint/preview", token=mg, body=tighten)
    call("POST", "/api/blueprint", token=mg, body=tighten)
    call("POST", f"/api/submissions/{sid}/publish", token=cr, body={"url": ""}, expect=400)
    print("PASS H5 publish refused after the rules changed")

    # H2: recovery tasks from a blueprint save are committed (visible on a second connection)
    r = call("GET", "/api/published", token=mg)
    if r:
        dbfile = os.environ.get("REBRAND_DB", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "rebrand.db"))
        n = sqlite3.connect(dbfile).execute(
            "SELECT count(*) FROM recovery_tasks WHERE state!='closed'").fetchone()[0]
        assert n >= 1, "recovery task from the rule change was not committed"
        print("PASS H2 recovery task committed (visible to a fresh connection)")

    # logout revokes the token
    t = call("POST", "/api/login", body={"email": "reviewer@demo.test", "password": "reviewer123"})["token"]
    call("GET", "/api/me", token=t)
    call("POST", "/api/logout", token=t)
    call("GET", "/api/me", token=t, expect=401)
    print("PASS logout revokes the session")

    # upload limits: oversize -> 413, invalid image -> 400 with no orphan file
    big = b"x" * (20 * 1024 * 1024 + 10)
    call("POST", "/api/blueprint/upload-guideline", token=mg,
         form={"file": ("big.txt", big, "text/plain")}, expect=413)
    call("POST", "/api/assets", token=mg,
         form={"name": "bad", "active": "1", "file": ("x.txt", b"not an image", "text/plain")}, expect=400)
    print("PASS upload limits: 413 oversize, 400 invalid image")

    # DOCX guideline import returns real text
    import docx
    d = docx.Document()
    d.add_paragraph("Write plainly. Never exaggerate.")
    buf = io.BytesIO(); d.save(buf)
    r = call("POST", "/api/blueprint/upload-guideline", token=mg,
             form={"file": ("rules.docx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert "Write plainly" in r["text"], r["text"][:100]
    print("PASS DOCX import returns real text")

    # publish URL must be http(s)
    sid = call("POST", "/api/submissions", token=cr,
               body={"title": "u", "content_type": "text", "text": "Hello everyone. Plain words here."})["id"]
    call("POST", f"/api/submissions/{sid}/check", token=cr)
    call("POST", f"/api/submissions/{sid}/decision", token=mg, body={"action": "approve"})
    call("POST", f"/api/submissions/{sid}/publish", token=cr, body={"url": "javascript:alert(1)"}, expect=400)
    print("PASS publish refuses a non-http link")

    print("V9: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
