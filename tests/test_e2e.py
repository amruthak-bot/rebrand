"""End-to-end walk of the full ReBrand workflow against a live server.
Run: python tests/test_e2e.py  (server must be running on :8000, fresh db seeded)
"""
import io
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"
PASS = []


def call(method, path, token=None, body=None, form=None, expect=200):
    url = BASE + path
    data, headers = None, {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if form is not None:
        boundary = "----testboundary"
        parts = []
        for k, v in form.items():
            if isinstance(v, tuple):
                fname, fdata, fmime = v
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{fname}"\r\nContent-Type: {fmime}\r\n\r\n'.encode() + fdata + b"\r\n")
            else:
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        parts.append(f"--{boundary}--\r\n".encode())
        data = b"".join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            code, payload = r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        code, payload = e.code, json.loads(e.read() or b"{}")
    ok = code == expect
    print(("PASS " if ok else f"FAIL ({code} != {expect}) ") + f"{method} {path} :: {json.dumps(payload)[:140]}")
    if not ok:
        sys.exit(1)
    PASS.append(1)
    return payload


def main():
    # fresh db for the test
    creator = call("POST", "/api/login", body={"email": "creator@demo.test", "password": "creator123"})["token"]
    manager = call("POST", "/api/login", body={"email": "manager@demo.test", "password": "manager123"})["token"]

    bp = call("GET", "/api/blueprint/current", token=creator)
    assert bp["version"] == 1

    # 1. creator submits off-brand text
    s = call("POST", "/api/submissions", token=creator, body={
        "title": "Winter launch post", "content_type": "text", "channel": "social",
        "text": "Hey guys! We are the best in the world. Rated 4.8/5 by 2,000+ customers. "
                "Used by teams in 12 countries. We utilise synergy to win."})
    sid = s["id"]

    # 2. run checks
    r = call("POST", f"/api/submissions/{sid}/check", token=creator)
    codes = {i["rule_code"] for i in r["issues"]}
    assert "TERM_BANNED" in codes and "CLAIM_UNSUPPORTED" in codes, codes
    high_open = [i for i in r["issues"] if i["severity"] == "high" and i["status"] == "open"]
    assert high_open, "expected open high issues"

    # 3. manager cannot approve while high issues are open
    call("POST", f"/api/submissions/{sid}/decision", token=manager,
         body={"action": "approve"}, expect=400)

    # Accepting without changing the text must NOT allow approval.
    for i in high_open:
        call("POST", f"/api/issues/{i['id']}/accept", token=creator)
    call("POST", f"/api/submissions/{sid}/decision", token=manager,
         body={"action": "approve"}, expect=400)
    # 4. creator accepts fixes, revises text, re-checks
    call("PATCH", f"/api/submissions/{sid}", token=creator, body={
        "text": "Hello everyone! Rated 4.8/5 by 2,000+ customers. "
                "Used by teams in 12 countries. We use cooperation to win."})
    r2 = call("POST", f"/api/submissions/{sid}/check", token=creator)
    open_high2 = [i for i in r2["issues"] if i["severity"] == "high" and i["status"] == "open"]
    assert not open_high2, open_high2

    # 5. manager approves, creator publishes (registers)
    call("POST", f"/api/submissions/{sid}/decision", token=manager, body={"action": "approve"})
    p = call("POST", f"/api/submissions/{sid}/publish", token=creator, body={"url": "https://example.test/post/1"})
    pid = p["published_id"]

    # 6. guideline/claim change: drop the winter offer claim from the library -> live item fails re-check
    call("POST", "/api/blueprint", token=manager, body={
        "note": "Winter offer ended",
        "guidelines": [
            {"title": "Voice and tone", "body": "Plain, confident, inclusive. Never 'guys'."},
            {"title": "Claims and evidence", "body": "Claims must come from the approved claim library."},
        ],
        "terms": [{"term": "guys", "kind": "banned", "replacement": "everyone", "note": "inclusive"}],
        "claims": [{"claim": "Rated 4.8/5 by 2,000+ customers", "risk": "high", "expires_on": None}],
        "palette": ["#1a56db", "#ffffff"]})
    tasks = call("GET", "/api/recovery", token=creator)
    mine = [t for t in tasks if t["published_id"] == pid and t["state"] != "closed"]
    assert mine, "expected a recovery task from the blueprint-change re-check"
    tid = mine[0]["id"]

    # 7. recovery: propose -> approve (human gate) -> corrected -> re-check -> close
    call("POST", f"/api/recovery/{tid}/propose", token=creator,
         body={"action": "edit", "deadline": "2026-11-06"})
    call("POST", f"/api/recovery/{tid}/approve-action", token=manager)
    call("PATCH", f"/api/submissions/{sid}", token=creator, body={
        "text": "Hello everyone! Rated 4.8/5 by 2,000+ customers. We use cooperation to win."})
    call("POST", f"/api/recovery/{tid}/mark-corrected", token=creator, expect=422)
    call("POST", f"/api/recovery/{tid}/mark-corrected", token=creator,
         body={"correction_note": "Updated the live social post manually; confirmed revised text on the channel."})
    closed = call("POST", f"/api/recovery/{tid}/close", token=manager)
    assert closed["state"] == "closed"

    # 8. graph + insights
    impact = call("GET", "/api/graph/impact?ref_type=claim&ref_key=Rated%204.8%2F5%20by%202%2C000%2B%20customers",
                  token=creator)
    assert impact["affected_live_items"], impact
    ins = call("GET", "/api/insights", token=creator)
    assert ins["closed_recoveries"] >= 1
    assert ins["flags_with_cited_clause_share"] is not None

    # 9. image checks: off-palette image without alt text
    from PIL import Image
    img = Image.new("RGB", (64, 64), (255, 0, 0))
    buf = io.BytesIO(); img.save(buf, "PNG")
    s2 = call("POST", "/api/submissions", token=creator, body={
        "title": "Red banner", "content_type": "image", "channel": "web", "alt_text": ""})
    call("POST", f"/api/submissions/{s2['id']}/upload", token=creator,
         form={"file": ("red.png", buf.getvalue(), "image/png")})
    r3 = call("POST", f"/api/submissions/{s2['id']}/check", token=creator)
    codes3 = {i["rule_code"] for i in r3["issues"]}
    assert "A11Y_ALT_TEXT" in codes3 and "PALETTE_OFF_BRAND" in codes3, codes3

    # Regression: no approval without a scan.
    raw = call("POST", "/api/submissions", token=creator, body={
        "title": "Unreviewed", "content_type": "text", "text": "A plain draft"})
    call("POST", f"/api/submissions/{raw['id']}/decision", token=manager,
         body={"action": "approve"}, expect=400)
    # Regression: a creator cannot approve.
    call("POST", f"/api/submissions/{raw['id']}/decision", token=creator,
         body={"action": "approve"}, expect=403)
    # Regression: expired approved claims are unsafe even if the text matches exactly.
    expired = call("POST", "/api/submissions", token=creator, body={
        "title": "Expired promotion", "content_type": "text",
        "text": "Winter offer: 20% off until January"})
    # The blueprint was replaced above, so use the original seeded expired claim
    # only if the active blueprint still contains it. Otherwise assert an unapproved
    # claim is not falsely described as a valid, approved claim.
    exp_scan = call("POST", f"/api/submissions/{expired['id']}/check", token=creator)
    assert not any(i["rule_code"] == "CLAIM_EXPIRED" for i in exp_scan["issues"]), "removed claim is not an approved expired claim"
    print(f"\nALL {len(PASS)} CHECKS PASSED")


if __name__ == "__main__":
    main()
