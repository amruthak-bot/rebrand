"""ReBrand - AI-powered brand damage recovery system.
FastAPI backend: blueprint, checks, approval workflow, published register,
recovery tracker, brand validity graph, insights. SQLite storage."""
import datetime
import threading
import hashlib
import json
import os
import re

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ai, db, extract, images, ocr, rules, security

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.environ.get("REBRAND_UPLOADS", os.path.join(BASE, "data", "uploads"))
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title="ReBrand", version="0.10.0")


@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp

# Uploads are read fully into memory, so cap them: a huge file would otherwise
# OOM the (small) container and take the demo down for everyone.
MAX_UPLOAD_BYTES = int(os.environ.get("REBRAND_MAX_UPLOAD_MB", "20")) * 1024 * 1024
# Text fields come in as JSON, not uploads, so they get their own caps.
MAX_TEXT_CHARS = int(os.environ.get("REBRAND_MAX_TEXT_CHARS", "500000"))
MAX_TITLE_CHARS = 300
MAX_ALT_CHARS = 2000
MAX_COMMENT_CHARS = 5000


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File too large. The limit is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    return data
if os.environ.get("REBRAND_AUTOSEED") == "1":
    from . import seed as _seed
    _seed.run()          # no-op when the database already has users
conn = db.init()
_db_lock = threading.RLock()


# ---------- auth ----------

def current_user(authorization: str = Header(default="")):
    token = authorization.replace("Bearer ", "").strip()
    user = security.user_for_token(conn, token)
    if not user:
        raise HTTPException(401, "Not signed in")
    return user


class LoginBody(BaseModel):
    email: str
    password: str


# Brute-force throttle: after several failed sign-ins for one email, pause that
# email for a few minutes. In-memory; a restart clears it.
_LOGIN_FAILS = {}
_LOGIN_WINDOW = 300
_LOGIN_MAX = 8


@app.post("/api/login")
def login(body: LoginBody):
    email = (body.email or "").strip().lower()
    now = db.now()
    fails = [t for t in _LOGIN_FAILS.get(email, []) if now - t < _LOGIN_WINDOW]
    _LOGIN_FAILS[email] = fails
    if len(fails) >= _LOGIN_MAX:
        raise HTTPException(429, "Too many failed sign-ins. Wait a few minutes and try again.")
    row = conn.execute("SELECT * FROM users WHERE email=?", (body.email,)).fetchone()
    if not row or not security.verify_password(body.password, row["pass_hash"]):
        fails.append(now)
        raise HTTPException(401, "Wrong email or password")
    _LOGIN_FAILS.pop(email, None)
    token = security.create_session(conn, row["id"])
    conn.commit()
    return {"token": token, "user": {"id": row["id"], "name": row["name"], "email": row["email"],
                                     "role": row["role"], "workspace_id": row["workspace_id"]}}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return {"id": user["id"], "name": user["name"], "email": user["email"],
            "role": user["role"], "workspace_id": user["workspace_id"]}


@app.post("/api/logout")
def logout(authorization: str = Header(default="")):
    token = authorization.replace("Bearer ", "").strip()
    security.revoke_session(conn, token)
    conn.commit()
    return {"ok": True}


# ---------- blueprint ----------

class BlueprintBody(BaseModel):
    note: str = ""
    guidelines: list = []   # [{title, body}]
    terms: list = []        # [{term, kind, replacement, note}]
    claims: list = []       # [{claim, risk, expires_on}]
    palette: list = []      # ["#rrggbb"]


_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _validate_blueprint(body):
    """Validate and normalize a blueprint payload BEFORE anything is written.
    Every bad input is a readable 400 here, never a 500 mid-insert."""
    if isinstance(body, BlueprintBody):
        body = {"note": body.note, "guidelines": body.guidelines,
                "terms": body.terms, "claims": body.claims, "palette": body.palette}
    guidelines = []
    for g in body.get("guidelines") or []:
        if not isinstance(g, dict):
            raise HTTPException(400, "Each guideline must be an object with title and body")
        guidelines.append({"title": str(g.get("title") or "Guideline").strip() or "Guideline",
                           "body": str(g.get("body") or "").strip()})
    terms = []
    for t in body.get("terms") or []:
        if not isinstance(t, dict):
            raise HTTPException(400, "Each term must be an object with term and kind")
        kind = t.get("kind")
        if kind not in ("banned", "preferred"):
            raise HTTPException(400, f"term kind must be banned|preferred: {t}")
        term = str(t.get("term") or "").strip()
        if not term:
            raise HTTPException(400, "A term is missing its word")
        terms.append({"term": term, "kind": kind,
                      "replacement": str(t.get("replacement") or "").strip(),
                      "note": str(t.get("note") or "").strip()})
    claims = []
    for c in body.get("claims") or []:
        if not isinstance(c, dict):
            raise HTTPException(400, "Each claim must be an object with claim and risk")
        claim = str(c.get("claim") or "").strip()
        if not claim:
            raise HTTPException(400, "A claim is missing its text")
        risk = str(c.get("risk") or "medium").strip().lower()
        if risk not in ("high", "medium", "low"):
            raise HTTPException(400, f"claim risk must be high|medium|low: {risk}")
        exp = c.get("expires_on") or None
        if exp is not None:
            exp = str(exp).strip() or None
        if exp:
            try:
                datetime.date.fromisoformat(exp)
            except ValueError:
                raise HTTPException(400, f"Claim expiry must be a YYYY-MM-DD date: {exp}")
        claims.append({"claim": claim, "risk": risk, "expires_on": exp})
    palette = []
    for p in body.get("palette") or []:
        hexv = str(p).strip()
        if not hexv:
            continue
        if not _HEX_RE.match(hexv):
            raise HTTPException(400, f"Brand colours must look like #1a56db (6 hex digits): {hexv}")
        palette.append(hexv.lower())
    return {"note": str(body.get("note") or "").strip(), "guidelines": guidelines,
            "terms": terms, "claims": claims, "palette": palette}


def _payload_hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


# Preview-before-save: the last previewed payload hash per (workspace, user).
# A rule change that was never previewed is refused with 409, so a manager
# always sees the blast radius before committing it.
_PREVIEWS = {}
_PREVIEW_TTL = 1800  # seconds


def _save_blueprint(ws, body, user_id, _validated=None):
    payload = _validated or _validate_blueprint(body)
    cur = db.current_version(conn, ws)
    version = (cur["version"] + 1) if cur else 1
    with _db_lock:
        try:
            r = conn.execute(
                "INSERT INTO blueprint_versions (workspace_id, version, note, created_by, created_at) VALUES (?,?,?,?,?)",
                (ws, version, payload["note"], user_id, db.now()))
            vid = r.lastrowid
            for g in payload["guidelines"]:
                conn.execute("INSERT INTO guidelines (version_id, title, body) VALUES (?,?,?)",
                             (vid, g["title"], g["body"]))
            for t in payload["terms"]:
                conn.execute("INSERT INTO terms (version_id, term, kind, replacement, note) VALUES (?,?,?,?,?)",
                             (vid, t["term"], t["kind"], t["replacement"], t["note"]))
            for c in payload["claims"]:
                conn.execute("INSERT INTO claims (version_id, claim, risk, expires_on) VALUES (?,?,?,?)",
                             (vid, c["claim"], c["risk"], c["expires_on"]))
            for hexv in payload["palette"]:
                conn.execute("INSERT INTO palette_colors (version_id, hex) VALUES (?,?)", (vid, hexv))
            db.audit(conn, ws, user_id, "blueprint.saved", "blueprint_version", vid, f"version {version}")
            # guideline change -> re-check all monitoring published items (Brand Validity Graph impact)
            impacted = _recheck_all_published(ws, reason=f"Blueprint updated to version {version}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"version_id": vid, "version": version, "impacted_published": impacted}


@app.post("/api/blueprint")
def save_blueprint(body: BlueprintBody, user=Depends(current_user)):
    if user["role"] not in ("manager", "reviewer"):
        raise HTTPException(403, "Only managers or reviewers can edit the blueprint")
    payload = _validate_blueprint(body)
    if os.environ.get("REBRAND_REQUIRE_PREVIEW", "1") != "0":
        key = (user["workspace_id"], user["id"])
        hashed, at = _PREVIEWS.get(key, (None, 0))
        if hashed != _payload_hash(payload) or db.now() - at > _PREVIEW_TTL:
            raise HTTPException(
                409, "Preview the impact first: run 'Preview the impact first' with these exact rules, "
                     "review what would break, then save.")
        del _PREVIEWS[key]
    return _save_blueprint(user["workspace_id"], None, user["id"], _validated=payload)


@app.post("/api/blueprint/upload-guideline")
async def upload_guideline(file: UploadFile = File(...), user=Depends(current_user)):
    data = await _read_upload(file)
    try:
        text = extract.extract_text(file.filename, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"filename": file.filename, "text": text}


@app.get("/api/blueprint/current")
def get_blueprint(user=Depends(current_user)):
    cur = db.current_version(conn, user["workspace_id"])
    if not cur:
        return {"version": None, "guidelines": [], "terms": [], "claims": [], "palette": []}
    bp = db.load_blueprint(conn, cur["id"])
    bp["version"] = cur["version"]
    bp["note"] = cur["note"]
    return bp


@app.post("/api/assets")
async def add_asset(name: str = Form(...), active: int = Form(1),
                    file: UploadFile = File(...), user=Depends(current_user)):
    if user["role"] not in ("manager", "reviewer"):
        raise HTTPException(403, "Only managers or reviewers can add assets")
    data = await _read_upload(file)
    try:
        pal = images.dominant_palette(data)
    except Exception:
        raise HTTPException(400, "File is not a readable image")
    sha = images.sha256_bytes(data)
    path = os.path.join(UPLOAD_DIR, sha[:16] + "_" + os.path.basename(file.filename))
    with open(path, "wb") as f:
        f.write(data)
    r = conn.execute(
        "INSERT INTO assets (workspace_id, name, sha256, path, palette_json, active, uploaded_by, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (user["workspace_id"], name, sha, path, images.palette_json(pal), active, user["id"], db.now()))
    db.audit(conn, user["workspace_id"], user["id"], "asset.added", "asset", r.lastrowid, name)
    conn.commit()
    return {"id": r.lastrowid, "name": name, "sha256": sha, "palette": pal, "active": bool(active)}


@app.get("/api/assets")
def list_assets(user=Depends(current_user)):
    rows = conn.execute("SELECT id, name, sha256, active, created_at FROM assets WHERE workspace_id=?",
                        (user["workspace_id"],)).fetchall()
    return [dict(r) for r in rows]


# ---------- submissions and checks ----------

class SubmissionBody(BaseModel):
    title: str
    content_type: str = "text"   # text | image | document
    channel: str = "web"
    text: str = ""
    alt_text: str = ""


# Previous Post Memory: local Published Register only; no external social scraping.
_MEMORY_STOP = {"about", "after", "again", "also", "been", "before", "brand", "company", "could", "from", "have", "into", "more", "offer", "only", "post", "posts", "product", "their", "there", "these", "this", "those", "with", "your", "will", "that", "they", "were", "what", "when", "where", "which", "while"}


def _memory_words(value):
    return {w for w in re.findall(r"[a-z]{4,}", (value or "").lower()) if w not in _MEMORY_STOP}


def _memory_numbers(value):
    # Only show potential differences; numbers are not proof of changed facts.
    return sorted(set(re.findall(r"(?<![\w])\d+(?:[.,]\d+)*(?:%|\+)?", value or "")))


class MemoryQuery(BaseModel):
    title: str = ""
    text: str = ""


@app.post("/api/memory/check")
def memory_check(body: MemoryQuery, user=Depends(current_user)):
    """Find related earlier published posts, without declaring which fact is true."""
    if not (body.title.strip() or body.text.strip()):
        return {"matches": [], "note": "Enter a title or draft text to compare."}
    draft_words = _memory_words(body.title + " " + body.text)
    draft_numbers = _memory_numbers(body.text)
    rows = conn.execute(
        "SELECT p.id, p.title, p.url, p.published_at, s.text "
        "FROM published p JOIN submissions s ON s.id=p.submission_id "
        "WHERE p.workspace_id=? ORDER BY p.published_at DESC LIMIT 150",
        (user["workspace_id"],)).fetchall()
    matches = []
    for row in rows:
        old_words = _memory_words(row["title"] + " " + (row["text"] or ""))
        shared = sorted(draft_words & old_words)
        if not shared:
            continue
        # Require at least two meaningful words, except when the draft is very short.
        if len(shared) < 2 and len(draft_words) > 2:
            continue
        old_numbers = _memory_numbers(row["text"])
        matches.append({
            "published_id": row["id"], "title": row["title"], "url": row["url"],
            "published_at": row["published_at"], "previous_text": (row["text"] or "")[:800],
            "shared_terms": shared[:8], "previous_numbers": old_numbers[:15],
            "draft_numbers": draft_numbers[:15],
            "possible_numeric_change": bool(old_numbers and draft_numbers and old_numbers != draft_numbers),
            "verification_note": "Possible numerical difference; verify the current facts before publishing." if old_numbers and draft_numbers and old_numbers != draft_numbers else "Related earlier post; check whether its information is still current."
        })
    matches.sort(key=lambda x: (-len(x["shared_terms"]), -x["published_at"]))
    return {"matches": matches[:3], "note": "Suggestions use only this workspace's Published Register. Similarity and numeric differences do not prove a contradiction or outdated fact."}


@app.post("/api/submissions")
def create_submission(body: SubmissionBody, user=Depends(current_user)):
    if body.content_type not in ("text", "image", "document"):
        raise HTTPException(400, "content_type must be text|image|document")
    if len(body.title) > MAX_TITLE_CHARS:
        raise HTTPException(400, f"Title is too long (max {MAX_TITLE_CHARS} characters).")
    if len(body.text) > MAX_TEXT_CHARS:
        raise HTTPException(400, f"Post text is too long (max {MAX_TEXT_CHARS} characters).")
    if len(body.alt_text) > MAX_ALT_CHARS:
        raise HTTPException(400, f"Alt text is too long (max {MAX_ALT_CHARS} characters).")
    cur = db.current_version(conn, user["workspace_id"])
    r = conn.execute(
        "INSERT INTO submissions (workspace_id, creator_id, title, content_type, channel, text, alt_text, "
        "state, version_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (user["workspace_id"], user["id"], body.title, body.content_type, body.channel, body.text,
         body.alt_text, "Draft", cur["id"] if cur else None, db.now(), db.now()))
    db.audit(conn, user["workspace_id"], user["id"], "submission.created", "submission", r.lastrowid, body.title)
    conn.commit()
    return {"id": r.lastrowid, "state": "Draft"}


@app.post("/api/submissions/{sid}/upload")
async def submission_upload(sid: int, file: UploadFile = File(...), user=Depends(current_user)):
    sub = _get_submission(sid, user)
    if sub["state"] not in ("Draft", "In Review", "In Recovery"):
        raise HTTPException(400, "Cannot upload to approved or published content")
    data = await _read_upload(file)
    ctype = sub["content_type"]
    # Validate BEFORE writing anything to disk, so a rejected upload leaves no orphan file.
    text = None
    if ctype in ("text", "document"):
        try:
            text = extract.extract_text(file.filename, data)
        except ValueError as e:
            raise HTTPException(400, str(e))
    else:
        try:
            images.dominant_palette(data)
        except Exception:
            raise HTTPException(400, "File is not a readable image")
    sha = images.sha256_bytes(data)
    path = os.path.join(UPLOAD_DIR, f"sub{sid}_" + sha[:12] + "_" + os.path.basename(file.filename))
    with open(path, "wb") as f:
        f.write(data)
    if ctype in ("text", "document"):
        conn.execute("UPDATE submissions SET text=?, file_path=?, updated_at=? WHERE id=?",
                     (text, path, db.now(), sid))
    else:
        conn.execute("UPDATE submissions SET file_path=?, updated_at=? WHERE id=?", (path, db.now(), sid))
    _invalidate_check(sid)
    conn.commit()
    return {"id": sid, "file_path": path, "bytes": len(data)}


def _get_submission(sid, user):
    row = conn.execute("SELECT * FROM submissions WHERE id=? AND workspace_id=?",
                       (sid, user["workspace_id"])).fetchone()
    if not row:
        raise HTTPException(404, "Submission not found")
    return dict(row)


def _store_issues(sid, issues):
    conn.execute("DELETE FROM issues WHERE submission_id=? AND status='open'", (sid,))
    for i in issues:
        conn.execute(
            "INSERT INTO issues (submission_id, rule_code, category, severity, evidence, clause, suggestion, "
            "source, uncertain, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sid, i["rule_code"], i["category"], i["severity"], i["evidence"], i["clause"],
             i.get("suggestion", ""), i.get("source", "rule"), i.get("uncertain", 0), db.now()))


def _run_checks(sub, blueprint, ws_assets):
    """Run all checks for a submission dict; return (issues, links, ai_note)."""
    text = sub.get("text") or ""
    all_issues, links = [], []
    if not text.strip() and not sub.get("file_path"):
        all_issues.append({
            "rule_code": "EMPTY_CONTENT", "category": "completeness", "severity": "high",
            "evidence": "The post has no text and no uploaded file.",
            "clause": "",
            "suggestion": "Write the post or upload the creative before asking for a review.",
        })
    if text:
        all_issues += rules.check_terminology(text, blueprint["terms"])
        claim_issues, used_claims = rules.check_claims(text, blueprint["claims"])
        all_issues += claim_issues
        links += [("claim", c) for c in used_claims]
        all_issues += rules.check_headings(text)
        all_issues += rules.check_reading_level(text)
    if sub.get("content_type") == "image" and sub.get("file_path"):
        with open(sub["file_path"], "rb") as f:
            data = f.read()
        img_issues, img_links, sha, pal = rules.check_image(
            data, sub.get("alt_text", ""), blueprint, ws_assets, images)
        all_issues += img_issues
        links += img_links
        # OCR: read the words inside the image and run the same text rules on them
        ocr_text, _ = ocr.read_text(data)
        if ocr_text:
            for i in rules.check_terminology(ocr_text, blueprint["terms"]):
                i["evidence"] = "Text read from the image (OCR): " + i["evidence"]
                all_issues.append(i)
            claim_issues, used = rules.check_claims(ocr_text, blueprint["claims"])
            for i in claim_issues:
                i["evidence"] = "Text read from the image (OCR): " + i["evidence"]
                all_issues.append(i)
            links += [("claim", c) for c in used]
    ai_issues, ai_note = ai.tone_check(text, blueprint)
    all_issues += ai_issues
    if not configured_guideline_citation_possible(blueprint):
        pass
    return all_issues, links, ai_note


def configured_guideline_citation_possible(blueprint):
    return bool(blueprint.get("guidelines"))


def _fingerprint(sub):
    """Bind approval to exact content and its brand-blueprint version."""
    payload = {k: sub.get(k) for k in ("title", "content_type", "channel", "text", "alt_text", "file_path", "version_id")}
    if sub.get("file_path") and os.path.isfile(sub["file_path"]):
        with open(sub["file_path"], "rb") as f:
            payload["file_hash"] = hashlib.sha256(f.read()).hexdigest()
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _invalidate_check(sid):
    conn.execute("UPDATE submissions SET checked_fingerprint='', approved_fingerprint='' WHERE id=?", (sid,))
    conn.execute("UPDATE issues SET status='resolved' WHERE submission_id=?", (sid,))


class SubmissionUpdate(BaseModel):
    text: str = None
    alt_text: str = None
    title: str = None


@app.patch("/api/submissions/{sid}")
def revise_submission(sid: int, body: SubmissionUpdate, user=Depends(current_user)):
    """Creator revises content (accepts a suggestion or edits manually)."""
    sub = _get_submission(sid, user)
    if sub["state"] not in ("Draft", "In Review", "In Recovery"):
        raise HTTPException(400, f"Cannot edit in state {sub['state']}")
    if body.text is not None:
        if len(body.text) > MAX_TEXT_CHARS:
            raise HTTPException(400, f"Post text is too long (max {MAX_TEXT_CHARS} characters).")
        conn.execute("UPDATE submissions SET text=? WHERE id=?", (body.text, sid))
    if body.alt_text is not None:
        if len(body.alt_text) > MAX_ALT_CHARS:
            raise HTTPException(400, f"Alt text is too long (max {MAX_ALT_CHARS} characters).")
        conn.execute("UPDATE submissions SET alt_text=? WHERE id=?", (body.alt_text, sid))
    if body.title is not None:
        if len(body.title) > MAX_TITLE_CHARS:
            raise HTTPException(400, f"Title is too long (max {MAX_TITLE_CHARS} characters).")
        conn.execute("UPDATE submissions SET title=? WHERE id=?", (body.title, sid))
    _invalidate_check(sid)
    conn.execute("UPDATE submissions SET updated_at=? WHERE id=?", (db.now(), sid))
    db.audit(conn, user["workspace_id"], user["id"], "submission.revised", "submission", sid, "")
    conn.commit()
    return {"id": sid, "state": _get_submission(sid, user)["state"]}


@app.post("/api/submissions/{sid}/check")
def check_submission(sid: int, user=Depends(current_user)):
    sub = _get_submission(sid, user)
    if sub["state"] not in ("Draft", "In Review"):
        raise HTTPException(400, "Only drafts or in-review content can be checked")
    cur = db.current_version(conn, user["workspace_id"])
    if not cur:
        raise HTTPException(400, "No brand blueprint yet. A manager or reviewer must create one first.")
    blueprint = db.load_blueprint(conn, cur["id"])
    assets = [dict(r) for r in conn.execute("SELECT * FROM assets WHERE workspace_id=?",
                                            (user["workspace_id"],)).fetchall()]
    sub["version_id"] = cur["id"]
    issues, links, ai_note = _run_checks(sub, blueprint, assets)
    conn.execute("UPDATE issues SET status='resolved' WHERE submission_id=?", (sid,))
    _store_issues(sid, issues)
    conn.execute("UPDATE submissions SET state='In Review', version_id=?, updated_at=?, checked_fingerprint=?, approved_fingerprint='' WHERE id=?",
                 (cur["id"], db.now(), _fingerprint(sub), sid))
    db.audit(conn, user["workspace_id"], user["id"], "submission.checked", "submission", sid,
             f"{len(issues)} issues against blueprint v{cur['version']}")
    conn.commit()
    return {"id": sid, "state": "In Review", "issues": _issues_for(sid), "ai_note": ai_note,
            "blueprint_version": cur["version"]}


def _issues_for(sid):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM issues WHERE submission_id=? ORDER BY "
        "CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, id", (sid,))]


@app.get("/api/submissions")
def list_submissions(user=Depends(current_user)):
    rows = conn.execute(
        "SELECT s.*, u.name AS creator_name FROM submissions s JOIN users u ON u.id=s.creator_id "
        "WHERE s.workspace_id=? ORDER BY s.updated_at DESC", (user["workspace_id"],)).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/submissions/{sid}")
def get_submission(sid: int, user=Depends(current_user)):
    sub = _get_submission(sid, user)
    sub["issues"] = _issues_for(sid)
    sub["approvals"] = [dict(r) for r in conn.execute(
        "SELECT a.*, u.name FROM approvals a JOIN users u ON u.id=a.user_id "
        "WHERE a.submission_id=? ORDER BY a.created_at", (sid,))]
    sub["comments"] = [dict(r) for r in conn.execute(
        "SELECT c.*, u.name FROM comments c JOIN users u ON u.id=c.user_id "
        "WHERE c.submission_id=? ORDER BY c.created_at", (sid,))]
    return sub


class IssueAction(BaseModel):
    reason: str = ""


@app.post("/api/issues/{iid}/accept")
def accept_issue(iid: int, user=Depends(current_user)):
    row = conn.execute(
        "SELECT i.*, s.workspace_id FROM issues i JOIN submissions s ON s.id=i.submission_id "
        "WHERE i.id=? AND s.workspace_id=?", (iid, user["workspace_id"])).fetchone()
    if not row:
        raise HTTPException(404, "Issue not found")
    if row["status"] != "open":
        raise HTTPException(400, "Only open issues can be accepted")
    # Accept means acknowledging the suggested correction, not declaring the content fixed.
    # A new scan must confirm the issue is gone before approval.
    conn.execute("UPDATE issues SET status='accepted' WHERE id=?", (iid,))
    db.audit(conn, user["workspace_id"], user["id"], "issue.accepted", "issue", iid, row["rule_code"])
    conn.commit()
    return {"id": iid, "status": "accepted"}


@app.post("/api/issues/{iid}/dispute")
def dispute_issue(iid: int, body: IssueAction, user=Depends(current_user)):
    row = conn.execute(
        "SELECT i.*, s.workspace_id FROM issues i JOIN submissions s ON s.id=i.submission_id "
        "WHERE i.id=? AND s.workspace_id=?", (iid, user["workspace_id"])).fetchone()
    if not row:
        raise HTTPException(404, "Issue not found")
    if row["status"] not in ("open", "accepted"):
        raise HTTPException(400, "Only open or accepted issues can be disputed")
    conn.execute("UPDATE issues SET status='disputed', dispute_reason=? WHERE id=?", (body.reason, iid))
    db.audit(conn, user["workspace_id"], user["id"], "issue.disputed", "issue", iid,
             f"{row['rule_code']}: {body.reason}")
    conn.commit()
    return {"id": iid, "status": "disputed"}


class CommentBody(BaseModel):
    body: str
    kind: str = "comment"


@app.post("/api/submissions/{sid}/comments")
def add_comment(sid: int, body: CommentBody, user=Depends(current_user)):
    _get_submission(sid, user)
    if not body.body.strip():
        raise HTTPException(400, "Comment is empty")
    if len(body.body) > MAX_COMMENT_CHARS:
        raise HTTPException(400, f"Comment is too long (max {MAX_COMMENT_CHARS} characters).")
    r = conn.execute("INSERT INTO comments (submission_id, user_id, body, kind, created_at) VALUES (?,?,?,?,?)",
                     (sid, user["id"], body.body, body.kind, db.now()))
    conn.commit()
    return {"id": r.lastrowid}


class DecisionBody(BaseModel):
    action: str          # approve | request_changes | reject
    reason: str = ""


@app.post("/api/submissions/{sid}/decision")
def decide(sid: int, body: DecisionBody, user=Depends(current_user)):
    if user["role"] not in ("manager", "reviewer"):
        raise HTTPException(403, "Only a manager or reviewer can approve or reject")
    if body.action not in ("approve", "request_changes", "reject"):
        raise HTTPException(400, "action must be approve|request_changes|reject")
    with _db_lock:
        sub = _get_submission(sid, user)
        if sub["state"] != "In Review":
            raise HTTPException(400, f"Only in-review content can get a decision (current state: {sub['state']}).")
        if body.action == "approve":
            if not sub.get("checked_fingerprint") or sub["checked_fingerprint"] != _fingerprint(sub):
                raise HTTPException(400, "Content must be checked again before approval")
            cur = db.current_version(conn, user["workspace_id"])
            if not cur or sub["version_id"] != cur["id"]:
                raise HTTPException(400, "Brand blueprint changed; recheck before approval")
        open_high = conn.execute(
            "SELECT count(*) AS n FROM issues WHERE submission_id=? AND status IN ('open','accepted','disputed') AND severity='high'",
            (sid,)).fetchone()["n"]
        if body.action == "approve" and open_high:
            raise HTTPException(400, f"{open_high} high-priority issue(s) still open. Resolve or dispute them first.")
        conn.execute("INSERT INTO approvals (submission_id, user_id, action, reason, created_at) VALUES (?,?,?,?,?)",
                     (sid, user["id"], body.action, body.reason, db.now()))
        new_state = {"approve": "Approved", "request_changes": "Draft", "reject": "Draft"}[body.action]
        conn.execute("UPDATE submissions SET state=?, updated_at=?, approved_fingerprint=? WHERE id=?",
                     (new_state, db.now(), _fingerprint(sub) if body.action == "approve" else "", sid))
        db.audit(conn, user["workspace_id"], user["id"], f"submission.{body.action}", "submission", sid, body.reason)
        conn.commit()
    return {"id": sid, "state": new_state}


# ---------- publish, register, recovery ----------

class PublishBody(BaseModel):
    url: str = ""


@app.post("/api/submissions/{sid}/publish")
def publish(sid: int, body: PublishBody, user=Depends(current_user)):
    sub = _get_submission(sid, user)
    if sub["state"] != "Approved":
        raise HTTPException(400, "Only approved content can be registered as published. "
                                 "An item never moves from Draft to Published without an approval record.")
    approved = conn.execute(
        "SELECT * FROM approvals WHERE submission_id=? AND action='approve' ORDER BY created_at DESC LIMIT 1",
        (sid,)).fetchone()
    if not approved:
        raise HTTPException(400, "No approval record found.")
    if not sub.get("approved_fingerprint") or sub["approved_fingerprint"] != _fingerprint(sub):
        raise HTTPException(400, "Approved content has changed; fresh review required")
    cur = db.current_version(conn, user["workspace_id"])
    if not cur or sub["version_id"] != cur["id"]:
        raise HTTPException(400, "Brand rules changed since this was approved. Run the check again and re-approve.")
    if body.url and not body.url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "The live link must start with http:// or https://")
    # re-run checks to build Brand Validity Graph links from what the item actually uses
    blueprint = db.load_blueprint(conn, sub["version_id"])
    assets = [dict(r) for r in conn.execute("SELECT * FROM assets WHERE workspace_id=?",
                                            (user["workspace_id"],)).fetchall()]
    issues, links, _ = _run_checks(sub, blueprint, assets)
    if any(i["severity"] == "high" for i in issues):
        raise HTTPException(400, "Content has high-priority violations; recheck and approve again")
    with _db_lock:
        r = conn.execute(
            "INSERT INTO published (submission_id, workspace_id, title, url, version_id, approver_id, published_at, state) "
            "VALUES (?,?,?,?,?,?,?, 'Monitoring')",
            (sid, user["workspace_id"], sub["title"], body.url, sub["version_id"], approved["user_id"], db.now()))
        pid = r.lastrowid
        for ref_type, ref_key in links:
            conn.execute("INSERT INTO published_links (published_id, ref_type, ref_key) VALUES (?,?,?)",
                         (pid, ref_type, ref_key))
        for g in blueprint["guidelines"]:
            conn.execute("INSERT INTO published_links (published_id, ref_type, ref_key) VALUES (?,?,?)",
                         (pid, "guideline", g["title"]))
        conn.execute("UPDATE submissions SET state='Published', updated_at=? WHERE id=?", (db.now(), sid))
        db.audit(conn, user["workspace_id"], user["id"], "content.published", "published", pid,
                 f"registered at blueprint v{blueprint['version_id']}")
        conn.commit()
    return {"published_id": pid, "state": "Monitoring", "graph_links": len(links) + len(blueprint["guidelines"])}


@app.get("/api/published")
def list_published(user=Depends(current_user)):
    rows = conn.execute(
        "SELECT p.*, u.name AS approver_name, v.version AS blueprint_version FROM published p "
        "JOIN users u ON u.id=p.approver_id JOIN blueprint_versions v ON v.id=p.version_id "
        "WHERE p.workspace_id=? ORDER BY p.published_at DESC", (user["workspace_id"],)).fetchall()
    return [dict(r) for r in rows]


def _triage(issues, is_live=True):
    sev_rank = {"high": 3, "medium": 2, "low": 1}
    worst = max((sev_rank.get(i["severity"], 0) for i in issues), default=0)
    if worst >= 3:
        return "high"
    if worst == 2:
        return "medium"
    return "low"


def _open_recovery(published_row, reason, issues):
    existing = conn.execute(
        "SELECT id FROM recovery_tasks WHERE published_id=? AND state!='closed'",
        (published_row["id"],)).fetchone()
    if existing:
        return existing["id"], False
    triage = _triage(issues)
    r = conn.execute(
        "INSERT INTO recovery_tasks (published_id, workspace_id, reason, triage, detected_at) VALUES (?,?,?,?,?)",
        (published_row["id"], published_row["workspace_id"], reason, triage, db.now()))
    conn.execute("UPDATE published SET state='In Recovery' WHERE id=?", (published_row["id"],))
    conn.execute("UPDATE submissions SET state='In Recovery', updated_at=? WHERE id=?",
                 (db.now(), published_row["submission_id"]))
    db.audit(conn, published_row["workspace_id"], None, "recovery.opened", "recovery_task", r.lastrowid, reason)
    return r.lastrowid, True


def _published_issues(published_row, blueprint, today=None):
    """Pure check of one published item against a given blueprint snapshot (no writes)."""
    sub = dict(conn.execute("SELECT * FROM submissions WHERE id=?",
                            (published_row["submission_id"],)).fetchone())
    assets = [dict(r) for r in conn.execute("SELECT * FROM assets WHERE workspace_id=?",
                                            (published_row["workspace_id"],)).fetchall()]
    issues, links, _ = _run_checks(sub, blueprint, assets)
    # Brand Validity Graph: claims the item was linked to at publish time
    graph_claims = [r["ref_key"] for r in conn.execute(
        "SELECT ref_key FROM published_links WHERE published_id=? AND ref_type='claim'",
        (published_row["id"],))]
    current_claims = {c["claim"]: c for c in blueprint["claims"]}
    today = today or datetime.date.today().isoformat()
    for used in graph_claims:
        if used not in current_claims:
            issues.append({
                "rule_code": "CLAIM_NO_LONGER_APPROVED", "category": "claims", "severity": "high",
                "evidence": f"Live item uses claim \"{used}\" which is no longer in the approved claim library.",
                "clause": "Claims rule: only claims in the current approved claim library may remain live.",
                "suggestion": "Remove the claim from the live item, or replace it with a current approved claim.",
                "source": "rule", "uncertain": 0,
            })
        else:
            c = current_claims[used]
            if c.get("expires_on") and c["expires_on"] < today:
                issues.append({
                    "rule_code": "CLAIM_EXPIRED", "category": "claims", "severity": "high",
                    "evidence": f"Live item uses claim \"{c['claim']}\" which expired on {c['expires_on']}.",
                    "clause": "Claims rule: expired claims must not remain in live content.",
                    "suggestion": "Remove or replace the expired claim in the live item.",
                    "source": "rule", "uncertain": 0,
                })
    return issues


def _recheck_published(published_row, reason):
    """Re-check one published item against the CURRENT blueprint. Returns (task_id, created, issues)."""
    cur = db.current_version(conn, published_row["workspace_id"])
    blueprint = db.load_blueprint(conn, cur["id"])
    issues = _published_issues(published_row, blueprint)
    open_issues = [i for i in issues]
    if open_issues:
        tid, created = _open_recovery(published_row, reason, open_issues)
        return tid, created, open_issues
    return None, False, []


def _recheck_all_published(ws, reason):
    impacted = []
    rows = conn.execute("SELECT * FROM published WHERE workspace_id=? AND state='Monitoring'", (ws,)).fetchall()
    for row in rows:
        tid, created, issues = _recheck_published(dict(row), reason)
        if created:
            impacted.append({"published_id": row["id"], "title": row["title"],
                             "recovery_task_id": tid, "issues": len(issues)})
    return impacted


@app.post("/api/published/{pid}/recheck")
def recheck_published(pid: int, user=Depends(current_user)):
    row = conn.execute("SELECT * FROM published WHERE id=? AND workspace_id=?",
                       (pid, user["workspace_id"])).fetchone()
    if not row:
        raise HTTPException(404, "Published item not found")
    tid, created, issues = _recheck_published(dict(row), f"Manual re-check by {user['name']}")
    conn.commit()
    return {"published_id": pid, "recovery_task_id": tid, "new_task": created,
            "issues": issues, "verdict": "DAMAGED - recovery opened" if issues else "OK against current blueprint"}


class ReportBody(BaseModel):
    reason: str


@app.post("/api/published/{pid}/report")
def report_published(pid: int, body: ReportBody, user=Depends(current_user)):
    row = conn.execute("SELECT * FROM published WHERE id=? AND workspace_id=?",
                       (pid, user["workspace_id"])).fetchone()
    if not row:
        raise HTTPException(404, "Published item not found")
    if not body.reason.strip():
        raise HTTPException(400, "Say what is wrong with the live post")
    tid, created, issues = _recheck_published(dict(row), f"Reported by {user['name']}: {body.reason}")
    if not created and not issues:
        # reported but rules find nothing: still open a task for human judgement
        tid, created = _open_recovery(dict(row), f"Reported by {user['name']}: {body.reason}",
                                      [{"severity": "medium"}])
    db.audit(conn, user["workspace_id"], user["id"], "published.reported", "published", pid, body.reason)
    conn.commit()
    return {"published_id": pid, "recovery_task_id": tid}


@app.get("/api/recovery")
def list_recovery(user=Depends(current_user)):
    rows = conn.execute(
        "SELECT r.*, p.title, p.url, u.name AS owner_name FROM recovery_tasks r "
        "JOIN published p ON p.id=r.published_id LEFT JOIN users u ON u.id=r.owner_id "
        "WHERE r.workspace_id=? ORDER BY r.detected_at DESC", (user["workspace_id"],)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d["closed_at"] and d["detected_at"]:
            d["days_to_close"] = round((d["closed_at"] - d["detected_at"]) / 86400, 2)
        out.append(d)
    return out


class CorrectionBody(BaseModel):
    correction_note: str


class RecoveryActionBody(BaseModel):
    action: str           # edit | replace | correction_note | unpublish
    owner_id: int = None
    deadline: str = ""


@app.post("/api/recovery/{tid}/propose")
def propose_recovery(tid: int, body: RecoveryActionBody, user=Depends(current_user)):
    row = _get_task(tid, user)
    if body.action not in ("edit", "replace", "correction_note", "unpublish"):
        raise HTTPException(400, "action must be edit|replace|correction_note|unpublish")
    conn.execute("UPDATE recovery_tasks SET action=?, owner_id=?, deadline=?, state='action_proposed' WHERE id=?",
                 (body.action, body.owner_id or user["id"], body.deadline, tid))
    db.audit(conn, user["workspace_id"], user["id"], "recovery.action_proposed", "recovery_task", tid, body.action)
    conn.commit()
    return {"id": tid, "state": "action_proposed"}


@app.post("/api/recovery/{tid}/approve-action")
def approve_recovery_action(tid: int, user=Depends(current_user)):
    row = _get_task(tid, user)
    if user["role"] not in ("manager", "reviewer"):
        raise HTTPException(403, "Only a manager or reviewer can approve a recovery action")
    if row["state"] != "action_proposed":
        raise HTTPException(400, "No proposed action to approve")
    conn.execute("UPDATE recovery_tasks SET state='in_progress', action_approved_by=? WHERE id=?",
                 (user["id"], tid))
    db.audit(conn, user["workspace_id"], user["id"], "recovery.action_approved", "recovery_task", tid, row["action"])
    conn.commit()
    return {"id": tid, "state": "in_progress"}


@app.post("/api/recovery/{tid}/mark-corrected")
def mark_corrected(tid: int, body: CorrectionBody, user=Depends(current_user)):
    row = _get_task(tid, user)
    if row["state"] != "in_progress":
        raise HTTPException(400, "Task is not in progress")
    if not body.correction_note.strip():
        raise HTTPException(400, "Describe how the external published item was corrected")
    conn.execute("UPDATE recovery_tasks SET state='recheck', corrected_at=?, correction_note=?, correction_confirmed_by=? WHERE id=?",
                 (db.now(), body.correction_note.strip(), user["id"], tid))
    db.audit(conn, user["workspace_id"], user["id"], "recovery.corrected", "recovery_task", tid, "")
    conn.commit()
    return {"id": tid, "state": "recheck"}


@app.post("/api/recovery/{tid}/close")
def close_recovery(tid: int, user=Depends(current_user)):
    row = _get_task(tid, user)
    if user["role"] not in ("manager", "reviewer"):
        raise HTTPException(403, "Only a manager or reviewer can close recovery")
    if row["state"] != "recheck" or not row.get("correction_note") or not row.get("correction_confirmed_by"):
        raise HTTPException(400, "Recovery requires a recorded external correction confirmation")
    pub = dict(conn.execute("SELECT * FROM published WHERE id=?", (row["published_id"],)).fetchone())
    sub = dict(conn.execute("SELECT * FROM submissions WHERE id=?", (pub["submission_id"],)).fetchone())
    cur = db.current_version(conn, user["workspace_id"])
    blueprint = db.load_blueprint(conn, cur["id"])
    assets = [dict(r) for r in conn.execute("SELECT * FROM assets WHERE workspace_id=?",
                                            (user["workspace_id"],)).fetchall()]
    issues, _, _ = _run_checks(sub, blueprint, assets)
    remaining = [i for i in issues if i["severity"] == "high"]
    if remaining:
        raise HTTPException(400, f"Re-check failed: {len(remaining)} high-priority issue(s) remain. "
                                 "Recovery cannot close until the re-check passes.")
    conn.execute("UPDATE recovery_tasks SET state='closed', closed_at=? WHERE id=?", (db.now(), tid))
    conn.execute("UPDATE published SET state='Monitoring' WHERE id=?", (pub["id"],))
    conn.execute("UPDATE submissions SET state='Monitoring', updated_at=? WHERE id=?", (db.now(), sub["id"]))
    db.audit(conn, user["workspace_id"], user["id"], "recovery.closed", "recovery_task", tid, "re-check passed")
    conn.commit()
    days = round((db.now() - row["detected_at"]) / 86400, 2)
    return {"id": tid, "state": "closed", "days_to_close": days}


def _get_task(tid, user):
    row = conn.execute("SELECT * FROM recovery_tasks WHERE id=? AND workspace_id=?",
                       (tid, user["workspace_id"])).fetchone()
    if not row:
        raise HTTPException(404, "Recovery task not found")
    return dict(row)


# ---------- brand validity graph + insights ----------

@app.get("/api/graph/impact")
def graph_impact(ref_type: str, ref_key: str, user=Depends(current_user)):
    """Which live items would be affected if this claim/term/asset/guideline changed."""
    rows = conn.execute(
        "SELECT p.id, p.title, p.url, p.state FROM published_links l JOIN published p ON p.id=l.published_id "
        "WHERE l.ref_type=? AND l.ref_key=? AND p.workspace_id=? AND p.state!='Closed'",
        (ref_type, ref_key, user["workspace_id"])).fetchall()
    return {"ref_type": ref_type, "ref_key": ref_key, "affected_live_items": [dict(r) for r in rows]}


@app.get("/api/insights")
def insights(user=Depends(current_user)):
    ws = user["workspace_id"]
    def q(sql, args=(ws,)):
        return [dict(r) for r in conn.execute(sql, args)]
    repeat = q("SELECT rule_code, category, count(*) AS n FROM issues i JOIN submissions s ON s.id=i.submission_id "
               "WHERE s.workspace_id=? GROUP BY rule_code ORDER BY n DESC")
    disputed = q("SELECT i.rule_code, count(*) AS n, group_concat(DISTINCT i.dispute_reason) AS reasons "
                 "FROM issues i JOIN submissions s ON s.id=i.submission_id "
                 "WHERE s.workspace_id=? AND i.status='disputed' GROUP BY i.rule_code ORDER BY n DESC")
    unclear_signals = [d for d in disputed if d["n"] >= 2]
    approvals = q("SELECT a.action, count(*) AS n FROM approvals a JOIN submissions s ON s.id=a.submission_id "
                  "WHERE s.workspace_id=? GROUP BY a.action")
    times = conn.execute(
        "SELECT avg(a.created_at - s.created_at) AS avg_secs FROM approvals a "
        "JOIN submissions s ON s.id=a.submission_id WHERE s.workspace_id=? AND a.action='approve'", (ws,)).fetchone()
    recovery = q("SELECT state, count(*) AS n FROM recovery_tasks WHERE workspace_id=? GROUP BY state")
    closed = conn.execute(
        "SELECT avg(closed_at - detected_at) AS avg_secs, count(*) AS n FROM recovery_tasks "
        "WHERE workspace_id=? AND state='closed'", (ws,)).fetchone()
    evidence_debt = q("SELECT count(*) AS n FROM issues i JOIN submissions s ON s.id=i.submission_id "
                      "WHERE s.workspace_id=? AND i.uncertain=1 AND i.status='open'")
    cited = conn.execute(
        "SELECT count(*) AS total, sum(CASE WHEN clause != '' THEN 1 ELSE 0 END) AS cited FROM issues i "
        "JOIN submissions s ON s.id=i.submission_id WHERE s.workspace_id=?", (ws,)).fetchone()
    return {
        "repeat_issues": repeat,
        "disputed_rules": disputed,
        "unclear_guideline_signals": unclear_signals,
        "approval_actions": approvals,
        "avg_time_to_approve_hours": round((times["avg_secs"] or 0) / 3600, 2),
        "recovery_by_state": recovery,
        "avg_days_to_close": round((closed["avg_secs"] or 0) / 86400, 2),
        "closed_recoveries": closed["n"],
        "open_evidence_debt": evidence_debt[0]["n"] if evidence_debt else 0,
        "flags_with_cited_clause_share": (
            round((cited["cited"] or 0) / cited["total"], 2) if cited["total"] else None),
    }


# ---------------------------------------------------------------------------
# Round 3 features: (1) impact preview, (2) claim expiry + renewal, (3) dispute learning
# ---------------------------------------------------------------------------
def _require_reviewer(user, what):
    if user["role"] not in ("manager", "reviewer"):
        raise HTTPException(403, f"Only a manager or reviewer can {what}")


@app.post("/api/blueprint/preview")
def preview_blueprint(body: BlueprintBody, user=Depends(current_user)):
    """Dry run: which live posts would newly fail if this blueprint were saved? Writes nothing."""
    _require_reviewer(user, "preview blueprint changes")
    ws = user["workspace_id"]
    payload = _validate_blueprint(body)
    _PREVIEWS[(ws, user["id"])] = (_payload_hash(payload), db.now())
    cur = db.current_version(conn, ws)
    current_bp = db.load_blueprint(conn, cur["id"]) if cur else {"guidelines": [], "terms": [], "claims": [], "palette": [], "version_id": None}
    cand = {"version_id": None, "guidelines": payload["guidelines"], "terms": payload["terms"],
            "claims": payload["claims"], "palette": payload["palette"]}
    rows = conn.execute("SELECT * FROM published WHERE workspace_id=? AND state='Monitoring'", (ws,)).fetchall()
    affected, cleared = [], []
    for row in rows:
        row = dict(row)
        before = {(i["rule_code"], i["evidence"]) for i in _published_issues(row, current_bp)}
        after_list = _published_issues(row, cand)
        new = [i for i in after_list if (i["rule_code"], i["evidence"]) not in before]
        after = {(i["rule_code"], i["evidence"]) for i in after_list}
        gone = [b for b in before if b not in after]
        if new:
            affected.append({
                "published_id": row["id"], "title": row["title"],
                "triage": _triage(new),
                "new_issues": [{"rule_code": i["rule_code"], "severity": i["severity"],
                                "evidence": i["evidence"], "cause_clause": i["clause"],
                                "suggestion": i["suggestion"]} for i in new]})
        if gone and not new:
            cleared.append({"published_id": row["id"], "title": row["title"], "issues_cleared": len(gone)})
    causes = {}
    for a in affected:
        for i in a["new_issues"]:
            causes[i["rule_code"]] = causes.get(i["rule_code"], 0) + 1
    return {
        "from_version": cur["version"] if cur else None,
        "checked_live_posts": len(rows),
        "newly_failing_posts": len(affected),
        "estimated_recovery_tasks": len(affected),
        "causes": [{"rule_code": k, "posts": v} for k, v in sorted(causes.items(), key=lambda x: -x[1])],
        "affected": affected, "would_clear": cleared,
        "saved": False,
        "note": "Preview only. Nothing was saved and no recovery task was opened.",
    }


def _expiry_status(exp, today, horizon):
    if not exp:
        return "no_expiry"
    if exp < today.isoformat():
        return "expired"
    if exp <= (today + datetime.timedelta(days=horizon)).isoformat():
        return "expiring_soon"
    return "current"


def _claims_expiry_data(ws, days):
    cur = db.current_version(conn, ws)
    if not cur:
        return {"claims": [], "horizon_days": days}
    bp = db.load_blueprint(conn, cur["id"])
    today = datetime.date.today()
    out = []
    for c in bp["claims"]:
        st = _expiry_status(c.get("expires_on"), today, days)
        if st == "no_expiry":
            continue
        users = [dict(r) for r in conn.execute(
            "SELECT p.id, p.title, p.state FROM published_links l JOIN published p ON p.id=l.published_id "
            "WHERE l.ref_type='claim' AND l.ref_key=? AND p.workspace_id=?", (c["claim"], ws))]
        out.append({"claim": c["claim"], "expires_on": c["expires_on"], "status": st,
                    "days_left": (datetime.date.fromisoformat(c["expires_on"]) - today).days,
                    "live_posts_using_it": users})
    out.sort(key=lambda x: x["expires_on"])
    return {"today": today.isoformat(), "horizon_days": days, "claims": out}


@app.get("/api/claims/expiry")
def claims_expiry(days: int = 30, user=Depends(current_user)):
    return _claims_expiry_data(user["workspace_id"], days)


def _scan_expiry(ws, days, actor_id, source="manual"):
    """Notify owners of expiring/expired claims and re-check affected live posts.
    Notices are de-duplicated per claim, post and day so the scheduler never spams."""
    info = _claims_expiry_data(ws, days)
    today = datetime.date.today().isoformat()
    notified, rechecked = [], []
    for c in info["claims"]:
        if c["status"] not in ("expired", "expiring_soon"):
            continue
        for p in c["live_posts_using_it"]:
            owner = conn.execute(
                "SELECT s.creator_id AS created_by FROM published p JOIN submissions s ON s.id=p.submission_id WHERE p.id=?",
                (p["id"],)).fetchone()
            verb = "expired on" if c["status"] == "expired" else "expires on"
            msg = (f"Claim \"{c['claim']}\" {verb} {c['expires_on']}; live post \"{p['title']}\" uses it. "
                   f"Renew the claim or fix the post.")
            dup = conn.execute("SELECT 1 FROM notifications WHERE workspace_id=? AND message=? AND date(created_at,'unixepoch','localtime')=?",
                               (ws, msg, today)).fetchone()
            if not dup:
                conn.execute(
                    "INSERT INTO notifications (workspace_id, user_id, kind, message, created_at) VALUES (?,?,?,?,?)",
                    (ws, owner["created_by"] if owner else None, "claim_expiry", msg, db.now()))
                notified.append({"post": p["title"], "claim": c["claim"], "status": c["status"]})
            if c["status"] == "expired" and p["state"] == "Monitoring":
                row = dict(conn.execute("SELECT * FROM published WHERE id=?", (p["id"],)).fetchone())
                tid, created, _ = _recheck_published(row, f"Claim expired: {c['claim']}")
                if created:
                    rechecked.append({"post": p["title"], "recovery_task_id": tid})
    db.audit(conn, ws, actor_id, "claims.expiry_scan", "claims", 0,
             f"{source}: {len(notified)} notices, {len(rechecked)} recoveries")
    conn.commit()
    return {"notices": notified, "recovery_opened": rechecked}


@app.post("/api/claims/expiry/scan")
def claims_expiry_scan(days: int = 30, user=Depends(current_user)):
    _require_reviewer(user, "run the expiry scan")
    return _scan_expiry(user["workspace_id"], days, user["id"])


def _scheduler_loop(hours):
    import threading, time
    while True:
        try:
            for w in conn.execute("SELECT id FROM workspaces").fetchall():
                with _db_lock:
                    _scan_expiry(w["id"], 30, None, source="scheduled")
        except Exception as e:  # never let the scheduler die
            print("expiry scheduler error:", e)
        time.sleep(max(60, hours * 3600))


@app.get("/api/notifications")
def notifications(user=Depends(current_user)):
    rows = conn.execute(
        "SELECT * FROM notifications WHERE workspace_id=? AND (user_id IS NULL OR user_id=? OR ?) "
        "ORDER BY created_at DESC LIMIT 50",
        (user["workspace_id"], user["id"], 1 if user["role"] in ("manager", "reviewer") else 0)).fetchall()
    return [dict(r) for r in rows]


class RenewBody(BaseModel):
    claim: str
    new_expires_on: str
    evidence_note: str = ""


@app.post("/api/claims/renew")
def renew_claim(body: RenewBody, user=Depends(current_user)):
    """Human-reviewed renewal: saves a new blueprint version with the claim's date extended,
    then re-checks live posts (closing the gap that expiry opened)."""
    _require_reviewer(user, "renew a claim")
    try:
        datetime.date.fromisoformat(body.new_expires_on)
    except ValueError:
        raise HTTPException(400, "new_expires_on must be YYYY-MM-DD")
    if not body.evidence_note.strip():
        raise HTTPException(400, "Say what evidence supports renewing this claim")
    ws = user["workspace_id"]
    cur = db.current_version(conn, ws)
    bp = db.load_blueprint(conn, cur["id"])
    if body.claim not in [c["claim"] for c in bp["claims"]]:
        raise HTTPException(404, "Claim not in the current library")
    claims = [{"claim": c["claim"], "risk": c["risk"],
               "expires_on": body.new_expires_on if c["claim"] == body.claim else c["expires_on"]}
              for c in bp["claims"]]
    nb = BlueprintBody(
        note=f"Renewed claim \"{body.claim}\" to {body.new_expires_on}: {body.evidence_note}",
        guidelines=[{"title": g["title"], "body": g["body"]} for g in bp["guidelines"]],
        terms=[{"term": t["term"], "kind": t["kind"], "replacement": t["replacement"], "note": t["note"]} for t in bp["terms"]],
        claims=claims, palette=bp["palette"])
    return _save_blueprint(ws, nb, user["id"])


@app.get("/api/guideline-suggestions")
def guideline_suggestions(user=Depends(current_user)):
    """Dispute learning: aggregate dispute reasons and reviewer decisions per rule and propose
    clearer wording. Proposals are drafts; a human must approve before any guideline changes."""
    ws = user["workspace_id"]
    rows = conn.execute(
        "SELECT i.rule_code, i.category, i.clause, i.suggestion, i.status, i.dispute_reason "
        "FROM issues i JOIN submissions s ON s.id=i.submission_id WHERE s.workspace_id=?", (ws,)).fetchall()
    by = {}
    for r in rows:
        d = by.setdefault(r["rule_code"], {"rule_code": r["rule_code"], "category": r["category"],
                                           "clause": r["clause"], "total": 0, "disputed": 0,
                                           "accepted": 0, "reasons": []})
        d["total"] += 1
        d["disputed"] += r["status"] == "disputed"
        d["accepted"] += r["status"] == "accepted"
        if r["dispute_reason"]:
            d["reasons"].append(r["dispute_reason"].strip())
    changes = conn.execute(
        "SELECT a.reason FROM approvals a JOIN submissions s ON s.id=a.submission_id "
        "WHERE s.workspace_id=? AND a.action IN ('request_changes','reject') AND a.reason!=''", (ws,)).fetchall()
    change_reasons = list(dict.fromkeys(r["reason"].strip() for r in changes))[:5]
    out = []
    for d in by.values():
        if d["disputed"] < 1:
            continue
        rate = d["disputed"] / d["total"]
        reasons = list(dict.fromkeys(d["reasons"]))
        words = {}
        for rs in reasons:
            for w in set(re.findall(r"[a-z']{4,}", rs.lower())):
                words[w] = words.get(w, 0) + 1
        common = [w for w, n in sorted(words.items(), key=lambda x: -x[1]) if n >= 2][:5]
        out.append({
            "rule_code": d["rule_code"], "clause": d["clause"],
            "times_flagged": d["total"], "times_disputed": d["disputed"],
            "dispute_rate": round(rate, 2),
            "confidence": "strong" if d["disputed"] >= 2 else "weak (one dispute)",
            "dispute_reasons": reasons[:8], "common_words": common,
            "proposed_wording": (
                f"Clarification for rule {d['rule_code']}: {d['clause']} "
                f"Writers have questioned this {d['disputed']} time(s), saying: "
                + "; ".join(f'\"{r}\"' for r in reasons[:3])
                + (f". Reviewers asked for changes citing: " + "; ".join(f'\"{r}\"' for r in change_reasons[:2]) if change_reasons else "")
                + ". Add an explicit example of what is and is not allowed, and name who can grant an exception."),
            "reviewer_change_reasons": change_reasons,
            "status": "draft - needs human approval",
        })
    out.sort(key=lambda x: (-x["times_disputed"], -x["dispute_rate"]))
    return {"suggestions": out, "reviewer_change_requests_seen": len(changes)}


class ClarifyBody(BaseModel):
    rule_code: str
    wording: str


@app.post("/api/guideline-suggestions/approve")
def approve_clarification(body: ClarifyBody, user=Depends(current_user)):
    """A human approves (and may edit) the wording; only then is a new blueprint version saved."""
    _require_reviewer(user, "approve a guideline clarification")
    if not body.wording.strip():
        raise HTTPException(400, "Wording is empty")
    ws = user["workspace_id"]
    cur = db.current_version(conn, ws)
    bp = db.load_blueprint(conn, cur["id"])
    guidelines = [{"title": g["title"], "body": g["body"]} for g in bp["guidelines"]]
    guidelines.append({"title": f"Clarification: {body.rule_code}", "body": body.wording.strip()})
    nb = BlueprintBody(
        note=f"Clarified {body.rule_code} from dispute feedback (approved by {user['name']})",
        guidelines=guidelines,
        terms=[{"term": t["term"], "kind": t["kind"], "replacement": t["replacement"], "note": t["note"]} for t in bp["terms"]],
        claims=[{"claim": c["claim"], "risk": c["risk"], "expires_on": c["expires_on"]} for c in bp["claims"]],
        palette=bp["palette"])
    return _save_blueprint(ws, nb, user["id"])


# ---------------------------------------------------------------------------
# Demo story: fictional data so every feature can be seen in a minute.
# ---------------------------------------------------------------------------
def _story_loaded(ws):
    return bool(conn.execute("SELECT 1 FROM events WHERE workspace_id=? AND action='demo.story_loaded'", (ws,)).fetchone())


def _load_demo_story(ws):
    users = {r["role"]: dict(r) for r in conn.execute("SELECT * FROM users WHERE workspace_id=?", (ws,))}
    cr, mg = users["creator"], users["manager"]
    today = datetime.date.today()
    soon = (today + datetime.timedelta(days=12)).isoformat()
    cur = db.current_version(conn, ws)
    bp = db.load_blueprint(conn, cur["id"])

    def bp_body(note, claims):
        return BlueprintBody(
            note=note,
            guidelines=[{"title": g["title"], "body": g["body"]} for g in bp["guidelines"]],
            terms=[{"term": t["term"], "kind": t["kind"], "replacement": t["replacement"], "note": t["note"]} for t in bp["terms"]],
            claims=claims, palette=bp["palette"])
    base_claims = [{"claim": c["claim"], "risk": c["risk"], "expires_on": c["expires_on"]} for c in bp["claims"]]
    ship = {"claim": "Free shipping on orders over $50", "risk": "medium", "expires_on": soon}
    _save_blueprint(ws, bp_body("Demo: add a short-lived shipping claim", base_claims + [ship]), mg["id"])

    def publish_post(title, text, url):
        sid = create_submission(SubmissionBody(title=title, channel="social", text=text), user=cr)["id"]
        res = check_submission(sid, user=cr)
        if any(i["severity"] == "high" for i in res["issues"]):
            raise RuntimeError("demo post has high issues: " + title)
        decide(sid, DecisionBody(action="approve", reason="Demo approval"), user=mg)
        return publish(sid, PublishBody(url=url), user=cr)["published_id"]

    publish_post("Welcome post", "Hello everyone! Our new brand guide is live. Read it before you publish.",
                 "https://example.test/demo/welcome")
    publish_post("Shipping post", "Hello everyone! Free shipping on orders over $50. Order today.",
                 "https://example.test/demo/shipping")
    publish_post("Reach post", "Hello everyone! Used by teams in 12 countries. Join them.",
                 "https://example.test/demo/reach")
    # a guideline change that breaks the Reach post -> recovery task opens by itself
    without = [c for c in base_claims if c["claim"] != "Used by teams in 12 countries"] + [ship]
    _save_blueprint(ws, bp_body("Demo: legal withdrew the 12-countries claim", without), mg["id"])
    # writers dispute the same rule twice -> dispute learning has data
    sid = create_submission(SubmissionBody(title="Community greeting", channel="social",
                                           text="Hey guys, welcome to the community. Hey guys, say hi."), user=cr)["id"]
    res = check_submission(sid, user=cr)
    for i in [x for x in res["issues"] if x["rule_code"] == "TERM_BANNED"][:2]:
        dispute_issue(i["id"], IssueAction(reason="Our community uses this casual greeting"), user=cr)
    db.audit(conn, ws, mg["id"], "demo.story_loaded", "workspace", ws, "fictional demo data")
    conn.commit()


@app.post("/api/demo/load")
def demo_load(user=Depends(current_user)):
    _require_reviewer(user, "load the demo story")
    if _story_loaded(user["workspace_id"]):
        raise HTTPException(409, "The demo story is already loaded in this workspace")
    _load_demo_story(user["workspace_id"])
    return {"loaded": True, "note": "Fictional demo data. Nothing was published anywhere."}


@app.get("/api/demo/status")
def demo_status():
    row = conn.execute("SELECT id FROM workspaces ORDER BY id LIMIT 1").fetchone()
    return {"story_loaded": bool(row and _story_loaded(row["id"]))}


class AiToneBody(BaseModel):
    items: list = []     # [{clause, evidence, suggestion}] produced in the browser by Puter AI
    provider: str = "puter"


@app.post("/api/submissions/{sid}/ai-tone")
def submit_ai_tone(sid: int, body: AiToneBody, user=Depends(current_user)):
    """Accept tone findings produced by a browser-side model (Puter, user-pays). The model output
    is untrusted: evidence must be quoted from the draft, otherwise the item is dropped; the clause
    must quote a guideline, otherwise the finding is stored as Uncertain for a human. AI findings
    are medium severity, so they never auto-approve or auto-block."""
    sub = _get_submission(sid, user)
    if sub["state"] not in ("Draft", "In Review"):
        raise HTTPException(400, "Only drafts or in-review content can get an AI tone review")
    cur = db.current_version(conn, user["workspace_id"])
    bp = db.load_blueprint(conn, cur["id"])
    guidelines = " ".join(g["body"] for g in bp["guidelines"]).lower()
    text = (sub.get("text") or "")
    kept, dropped = 0, 0
    conn.execute("UPDATE issues SET status='resolved' WHERE submission_id=? AND source='ai' AND status IN ('open','accepted')", (sid,))
    for it in body.items[:10]:
        if not isinstance(it, dict):
            dropped += 1
            continue
        evidence = str(it.get("evidence") or "").strip()[:400]
        clause = str(it.get("clause") or "").strip()[:400]
        if not evidence or evidence.lower() not in text.lower():
            dropped += 1          # not a quote from the draft: treat as invented
            continue
        cited = bool(clause) and clause.lower() in guidelines
        conn.execute(
            "INSERT INTO issues (submission_id, rule_code, category, severity, evidence, clause, suggestion, "
            "source, uncertain, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sid, "AI_TONE", "tone", "medium", f'Quoted from the draft: "{evidence}"',
             clause if cited else (clause or "No guideline clause cited"),
             str(it.get("suggestion") or "")[:400], "ai", 0 if cited else 1, db.now()))
        kept += 1
    db.audit(conn, user["workspace_id"], user["id"], "submission.ai_tone", "submission", sid,
             f"provider={body.provider} kept={kept} dropped={dropped}")
    conn.commit()
    return {"kept": kept, "dropped_not_quoted_from_draft": dropped, "issues": _issues_for(sid)}


@app.get("/api/audit")
def audit_trail(user=Depends(current_user)):
    rows = conn.execute(
        "SELECT e.*, u.name AS actor FROM events e LEFT JOIN users u ON u.id=e.actor_id "
        "WHERE e.workspace_id=? ORDER BY e.created_at DESC LIMIT 100", (user["workspace_id"],)).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/health")
def health():
    return {"ok": True, "version": app.version, "ai_layer": ai.configured()}


if os.environ.get("REBRAND_DEMO_STORY") == "1":
    _ws = conn.execute("SELECT id FROM workspaces ORDER BY id LIMIT 1").fetchone()
    if _ws and not _story_loaded(_ws["id"]):
        try:
            _load_demo_story(_ws["id"])
        except Exception as e:
            # demo data must never take the app down at boot
            print("ReBrand: demo story failed to load:", e)
            conn.rollback()

_hours = float(os.environ.get("REBRAND_SCAN_HOURS", "0") or 0)
if _hours > 0:
    threading.Thread(target=_scheduler_loop, args=(_hours,), daemon=True).start()

# static frontend
static_dir = os.path.join(BASE, "static")


@app.get("/")
def index():
    return FileResponse(os.path.join(static_dir, "index.html"))


app.mount("/static", StaticFiles(directory=static_dir), name="static")
