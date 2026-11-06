"""ReBrand - AI-powered brand damage recovery system.
FastAPI backend: blueprint, checks, approval workflow, published register,
recovery tracker, brand validity graph, insights. SQLite storage."""
import datetime
import hashlib
import json
import os
import re

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ai, db, extract, images, rules, security

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE, "data", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title="ReBrand", version="0.1.0")
conn = db.init()


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


@app.post("/api/login")
def login(body: LoginBody):
    row = conn.execute("SELECT * FROM users WHERE email=?", (body.email,)).fetchone()
    if not row or not security.verify_password(body.password, row["pass_hash"]):
        raise HTTPException(401, "Wrong email or password")
    token = security.create_session(conn, row["id"])
    conn.commit()
    return {"token": token, "user": {"id": row["id"], "name": row["name"], "email": row["email"],
                                     "role": row["role"], "workspace_id": row["workspace_id"]}}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return {"id": user["id"], "name": user["name"], "email": user["email"],
            "role": user["role"], "workspace_id": user["workspace_id"]}


# ---------- blueprint ----------

class BlueprintBody(BaseModel):
    note: str = ""
    guidelines: list = []   # [{title, body}]
    terms: list = []        # [{term, kind, replacement, note}]
    claims: list = []       # [{claim, risk, expires_on}]
    palette: list = []      # ["#rrggbb"]


def _save_blueprint(ws, body: BlueprintBody, user_id):
    cur = db.current_version(conn, ws)
    version = (cur["version"] + 1) if cur else 1
    r = conn.execute(
        "INSERT INTO blueprint_versions (workspace_id, version, note, created_by, created_at) VALUES (?,?,?,?,?)",
        (ws, version, body.note, user_id, db.now()))
    vid = r.lastrowid
    for g in body.guidelines:
        conn.execute("INSERT INTO guidelines (version_id, title, body) VALUES (?,?,?)",
                     (vid, g.get("title", "Guideline"), g.get("body", "")))
    for t in body.terms:
        if t.get("kind") not in ("banned", "preferred"):
            raise HTTPException(400, f"term kind must be banned|preferred: {t}")
        conn.execute("INSERT INTO terms (version_id, term, kind, replacement, note) VALUES (?,?,?,?,?)",
                     (vid, t["term"], t["kind"], t.get("replacement", ""), t.get("note", "")))
    for c in body.claims:
        conn.execute("INSERT INTO claims (version_id, claim, risk, expires_on) VALUES (?,?,?,?)",
                     (vid, c["claim"], c.get("risk", "medium"), c.get("expires_on")))
    for hexv in body.palette:
        conn.execute("INSERT INTO palette_colors (version_id, hex) VALUES (?,?)", (vid, hexv))
    db.audit(conn, ws, user_id, "blueprint.saved", "blueprint_version", vid, f"version {version}")
    conn.commit()
    # guideline change -> re-check all monitoring published items (Brand Validity Graph impact)
    impacted = _recheck_all_published(ws, reason=f"Blueprint updated to version {version}")
    return {"version_id": vid, "version": version, "impacted_published": impacted}


@app.post("/api/blueprint")
def save_blueprint(body: BlueprintBody, user=Depends(current_user)):
    if user["role"] not in ("manager", "reviewer"):
        raise HTTPException(403, "Only managers or reviewers can edit the blueprint")
    return _save_blueprint(user["workspace_id"], body, user["id"])


@app.post("/api/blueprint/upload-guideline")
async def upload_guideline(file: UploadFile = File(...), user=Depends(current_user)):
    data = await file.read()
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
    data = await file.read()
    sha = images.sha256_bytes(data)
    path = os.path.join(UPLOAD_DIR, sha[:16] + "_" + os.path.basename(file.filename))
    with open(path, "wb") as f:
        f.write(data)
    try:
        pal = images.dominant_palette(data)
    except Exception:
        raise HTTPException(400, "File is not a readable image")
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
    data = await file.read()
    sha = images.sha256_bytes(data)
    path = os.path.join(UPLOAD_DIR, f"sub{sid}_" + sha[:12] + "_" + os.path.basename(file.filename))
    with open(path, "wb") as f:
        f.write(data)
    ctype = sub["content_type"]
    if ctype in ("text", "document"):
        try:
            text = extract.extract_text(file.filename, data)
        except ValueError as e:
            raise HTTPException(400, str(e))
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
    if (sub.get("content_type") == "image" and not sub.get("file_path")) or (
            sub.get("content_type") != "image" and not text.strip()):
        all_issues.append({
            "rule_code": "CONTENT_MISSING", "category": "content", "severity": "high",
            "evidence": "There is no image to check." if sub.get("content_type") == "image" else "There is no text to check.",
            "clause": "Content must be supplied before it can be checked and approved.",
            "suggestion": "Upload an image." if sub.get("content_type") == "image" else "Write a post or upload a document containing text.",
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
        conn.execute("UPDATE submissions SET text=? WHERE id=?", (body.text, sid))
    if body.alt_text is not None:
        conn.execute("UPDATE submissions SET alt_text=? WHERE id=?", (body.alt_text, sid))
    if body.title is not None:
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
    sub = _get_submission(sid, user)
    if body.action not in ("approve", "request_changes", "reject"):
        raise HTTPException(400, "action must be approve|request_changes|reject")
    if body.action == "approve":
        if sub["state"] != "In Review" or not sub.get("checked_fingerprint") or sub["checked_fingerprint"] != _fingerprint(sub):
            raise HTTPException(400, "Content must be checked again before approval")
        if sub["version_id"] != db.current_version(conn, user["workspace_id"])["id"]:
            raise HTTPException(400, "Brand blueprint changed; recheck before approval")
    open_high = conn.execute(
        "SELECT count(*) AS n FROM issues WHERE submission_id=? AND status IN ('open','accepted','disputed') AND severity='high'",
        (sid,)).fetchone()["n"]
    if body.action == "approve" and open_high:
        raise HTTPException(400, f"{open_high} high-priority issue(s) still open. Fix the content and recheck first.")
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
    # re-run checks to build Brand Validity Graph links from what the item actually uses
    blueprint = db.load_blueprint(conn, sub["version_id"])
    assets = [dict(r) for r in conn.execute("SELECT * FROM assets WHERE workspace_id=?",
                                            (user["workspace_id"],)).fetchall()]
    issues, links, _ = _run_checks(sub, blueprint, assets)
    if any(i["severity"] == "high" for i in issues):
        raise HTTPException(400, "Content has high-priority violations; recheck and approve again")
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


def _recheck_published(published_row, reason):
    """Re-check one published item against the CURRENT blueprint. Returns (task_id, created, issues)."""
    sub = dict(conn.execute("SELECT * FROM submissions WHERE id=?",
                            (published_row["submission_id"],)).fetchone())
    cur = db.current_version(conn, published_row["workspace_id"])
    blueprint = db.load_blueprint(conn, cur["id"])
    assets = [dict(r) for r in conn.execute("SELECT * FROM assets WHERE workspace_id=?",
                                            (published_row["workspace_id"],)).fetchall()]
    issues, links, _ = _run_checks(sub, blueprint, assets)
    # Brand Validity Graph: claims the item was linked to at publish time
    graph_claims = [r["ref_key"] for r in conn.execute(
        "SELECT ref_key FROM published_links WHERE published_id=? AND ref_type='claim'",
        (published_row["id"],))]
    current_claims = {c["claim"]: c for c in blueprint["claims"]}
    today = datetime.date.today().isoformat()
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


@app.get("/api/audit")
def audit_trail(user=Depends(current_user)):
    rows = conn.execute(
        "SELECT e.*, u.name AS actor FROM events e LEFT JOIN users u ON u.id=e.actor_id "
        "WHERE e.workspace_id=? ORDER BY e.created_at DESC LIMIT 100", (user["workspace_id"],)).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/health")
def health():
    return {"ok": True, "ai_layer": ai.configured()}


# static frontend
static_dir = os.path.join(BASE, "static")


@app.get("/")
def index():
    return FileResponse(os.path.join(static_dir, "index.html"))


app.mount("/static", StaticFiles(directory=static_dir), name="static")
