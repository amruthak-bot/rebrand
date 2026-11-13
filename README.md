# ReBrand: Brand Damage Recovery System

CodeNexus India 2026, Round 3 (final) build. Problem statement by Inkloom AI: intelligent
brand-governance platform. Team: RASHI INNOVATORS (Amrutha K - team leader; Akshay Kammar).

ReBrand checks content **before publication** against an organisation's own brand
blueprint (guidelines, terminology, approved claims, assets, palette, accessibility
rules), explains every issue with the guideline behind it, and suggests corrections
that preserve the creator's intent. After publication it keeps a register of live
items and **recovers damage**: when a guideline changes or a claim expires, affected
live items are re-checked, damaged ones become tracked recovery tasks, and every
corrective action requires human approval before closure.

## Interface (current design, 13 November - simple, calm, human)

The backend and API are unchanged; only the words, colours and layout changed.
No feature was added or removed in this redesign.

- **One job per screen.** Sign-in opens on the "What's new in Round 3" guide, and "Write a new post" is one click away. Every
  screen has one main button, in plain words ("Check my post", "Approve",
  "Mark as published"). Sections are named for what they are: Brand rules,
  New post, Review, Live posts, Posts to fix, Simple numbers.
- **Plain words, not jargon.** Issues say "Stop: fix this first",
  "Check this" or "Small fix" instead of severity codes, and every flag says
  what was found, why it matters, and how to fix it. Empty screens explain
  what will appear there, instead of showing a blank list.
- **Colours chosen for stressed people doing careful work.** Brand and social
  teams check posts under time pressure, so the interface is calm first:
  warm paper background (#F6F1E7, like a printed page, easy on the eyes),
  signal red (#C4341D) reserved for risk and primary actions,
  warm amber (#B7791F) for "look at this". No blue/purple gradients, no
  glass panels, no generic AI look. Headings are a warm serif (Fraunces
  italic for the accent line); body text is Space Grotesk; small-caps
  labels are IBM Plex Mono. Red means stop or act, amber means check. The
  same meaning everywhere in the app, so a new user learns it once.
  (Earlier November builds used a green/amber palette; the 13 November
  editorial redesign superseded it. Layout and wording principles are
  unchanged.)
- **Hand-finished details (13 November, final polish).** Numbered outline
  numerals sit behind the three steps, a rotated "CodeNexus Round 3 final"
  stamp marks the hero, a hand-drawn red arrow with a handwritten "start
  here" note points at the first action, a marker highlight underlines one
  key word on the sign-in screen, and an ink footer band closes each page
  with the wordmark and the team line. Small screens get the same design
  with adjusted sizes. All layout CSS is self-hosted in the page, so the
  interface renders identically even if the optional icon/font CDNs are
  unreachable.

## Design principles (from the Round 1 plan)

- **Explain, do not just reject.** Every flag shows what was found, which guideline
  clause applies, and a suggested fix.
- **Human decides.** Publication, correction and unpublishing all require a named
  human approval. The system never auto-publishes or auto-deletes.
- **Evidence, not confidence alone.** Priorities come from the rule type and the
  evidence found. AI findings that cannot cite a blueprint clause are marked
  **Uncertain** and routed to a human (Evidence Debt).
- **Recovery is governance.** A published error is tracked to closure with an
  owner, deadline, approved action, re-check and days-to-close.
- **Blame the rule, not the writer.** Repeated disputes on a rule surface the
  guideline itself as unclear.

## Stack

Python + FastAPI backend, SQLite storage (schema portable to PostgreSQL), vanilla
JavaScript + Tailwind CSS frontend served by the backend, Pillow for image checks.
No paid services. The optional AI tone layer runs only when `REBRAND_LLM_KEY` is
set; without a key the product works fully with deterministic rules and marks tone
review as Uncertain for a human.

## Run locally

```bash
pip install -r requirements.txt
python -m app.seed      # creates the demo workspace and users
python run.py           # serves http://127.0.0.1:8000
```

Demo logins (local demo only):
- `creator@demo.test` / `creator123` (Creator)
- `manager@demo.test` / `manager123` (Manager)
- `reviewer@demo.test` / `reviewer123` (Reviewer / brand manager)

## End-to-end test

```bash
python run.py &          # server on :8000
python tests/test_e2e.py # 34 checks: full workflow, both content types
```

The test walks the whole product: submit off-brand text, deterministic flags with
clauses, approval blocked while high issues are open, creator revision, approval,
publish + register, a blueprint change that re-checks live content and opens a
recovery task, human-approved corrective action, re-check and closure, Brand
Validity Graph impact query, insights, and image checks (palette + alt text).

## Feature map (Round 1 plan, Section 5)

| Plan feature | Where |
|---|---|
| Brand Blueprint import (PDF/DOCX/TXT extraction, versioned) | `POST /api/blueprint`, `/api/blueprint/upload-guideline`, Blueprint tab |
| Text check (terminology, claims, clause citations) | `app/rules.py` |
| Explain + Suggest (evidence, guideline, priority, fix, Uncertain) | issues model + Review queue |
| Approval workflow (roles, comments, history, human gate) | `/api/submissions/{id}/decision`, blocked while high issues open |
| Published Register | `/api/published`, Published register tab |
| Damage detection + Recovery tracker | `/api/recovery`, Recovery tab |
| Image check (asset hash, palette, alt text) | `app/images.py`, `rules.check_image` |
| Accessibility check (alt text, headings, reading level, contrast helper) | `rules.check_headings`, `check_reading_level`, `images.contrast_ratio` |
| Insights dashboard (repeat issues, disputes, timing, cited-clause share) | `/api/insights`, Insights tab |
| Brand Validity Graph (links live items to claims/guidelines; impact list) | `published_links`, `/api/graph/impact` |
| Evidence Debt (Uncertain flags, never silently passed) | `uncertain` flags, insights |
| Guideline repair signal (repeatedly disputed rules) | insights: unclear_guideline_signals |
| Privacy controls (workspace isolation, hashed passwords, AI disclosure) | per-workspace queries, PBKDF2, AI-assisted badge |

Content states: Draft -> In Review -> Approved -> Published -> Monitoring ->
In Recovery -> Closed. No Draft-to-Published move without an approval record;
no recovery closure without a passing re-check.

## Architecture

Browser -> FastAPI -> rule engine (+ optional AI layer) -> SQLite + asset store
-> insights. Blueprint store holds versioned guidelines/terms/claims/palette;
workflow store holds submissions, issues, approvals, recovery tasks; every state
change writes an audit event. No component trains on organisation data.

## Disclosures

- Built fresh in the official Round 2 build window (4-7 November 2026). No prior
  project code is submitted as this product.
- Code was drafted with AI assistance, as the Round 1 plan disclosed for the plan
  itself; standard libraries and frameworks are used under their licences
  (FastAPI, Uvicorn, Pillow, pypdf, Tailwind CSS via CDN).
- Demo data (demo users, sample blueprint) is fictional and for local judging only.

## Known limits (MVP honesty)

- OCR (RapidOCR) reads text inside image posts and runs the same rules on it.
  Accuracy on real-world photos and stylised text is not benchmarked; findings
  go to a human like every other check.
- AI tone check requires the operator to supply a model key via environment
  variables; without it, tone review is routed to humans as Uncertain.
- Auth is demo-grade role-based access, not SSO.


## Round 2 safety fixes (6 November)
- Scans and approvals are tied to exact content and blueprint versions; content changes invalidate scans.
- Accepting/disputing a high-priority finding cannot bypass approval; fix and re-scan.
- Expired approved claims are flagged at initial submission.
- Recovery correction requires a human's written confirmation of the external change; closure remains reviewer-only with recheck. This is **manual confirmation**, not automated verification of a live website.
- Schema upgrades are applied to existing SQLite databases.
- The uploaded source bundle did **not** contain the original `static/app.js`; this package includes a replacement JavaScript frontend. Browser walkthrough of the live deployment was completed on 12 November.

## Previous Post Memory Check (Round 2 small addition)
On **Submit content**, choose **Compare with previous posts**. The feature compares the draft with up to 150 published items in the same workspace, shows up to three related posts with dates, and highlights possible numerical differences. It does not scrape external sites or claim a previous figure is false; a human must verify. This is an advisory check, not an approval bypass.

## Final Round 2 build
- Includes the Previous Post Memory Check on the Submit content screen.
- Fresh-install verification: end-to-end API checks, expired-claim safety check, and JavaScript syntax check passed (superseded by the Round 3 suites below).
- Public hosting (Modal) and full browser interactions were verified on 12 November.
- For production hosting, configure persistent storage and production authentication; the seeded accounts are demo-only.

## Round 3 additions (9 November 2026)

- Impact preview: `POST /api/blueprint/preview` and the "Preview the impact first" button show which live posts would newly fail before a rules version is saved. Nothing is saved.
- Claim expiry and renewal: `GET /api/claims/expiry`, `POST /api/claims/expiry/scan` (notices + recovery for expired claims), `POST /api/claims/renew` (needs an evidence note, creates a new rules version). UI: "Plan ahead" tab. The scan runs on demand and on an in-process timer (`REBRAND_SCAN_HOURS`, 24 in the deploy configs).
- Dispute learning: `GET /api/guideline-suggestions` aggregates dispute reasons per rule and drafts clearer wording; `POST /api/guideline-suggestions/approve` saves it only after a manager or reviewer approves. The wording is template-based, not AI-generated.
- Tests: `python tests/test_round3.py` (fresh seeded db), plus the unchanged e2e and safety tests.
- Demo story: `POST /api/demo/load` (or the button in Plan ahead) adds fictional data: 3 live posts, 1 fix task opened by a guideline change, a claim expiring in 12 days, 2 disputes. Set `REBRAND_AUTOSEED=1` and `REBRAND_DEMO_STORY=1` (see `render.yaml`) so a fresh deploy seeds itself, which fixes the "data disappears after redeploy" problem on a free host without a disk. Tests: `tests/test_demo_story.py`.
- Judge quick-start buttons on the sign-in page and a "Fill in a sample off-brand post" button in New post.
- Optional Puter AI tone review (button in Review, "Optional: AI tone review (Puter)"): runs in the browser on the signed-in person's own Puter account (user-pays, no key on our side). The server accepts the findings via `POST /api/submissions/{id}/ai-tone`, drops any whose evidence is not quoted from the draft, marks findings without a guideline quote as Uncertain, and keeps them medium severity so a human still decides. The core app, storage and approval gate stay on the server and work without Puter.
- OCR for image posts (optional): `pip install -r requirements-ocr.txt` adds RapidOCR (PaddleOCR models on ONNX Runtime, CPU only). Words read from an image go through the same terminology and claim rules, with evidence marked "Text read from the image (OCR)". Without the package, image checks run as before. Test: `tests/test_ocr.py`.
- Deployment: the app runs on Modal (`modal_app.py`) as one always-warm container (no cold start for judges) with data on a persistent Modal Volume, auto-seed and demo story on start. Live demo: https://akshaykammar31--rebrand-web.us-east.modal.run . `render.yaml` remains as a free fallback.

## Round 3 final additions (12 November 2026)

- "What's new in Round 3" tab: a judge-facing guide mapping each promised improvement to where to try it.
- "Activity" tab: the audit trail (`GET /api/audit`) rendered in the UI - every check, approval, publication and fix with who did it and when. Test: `tests/test_activity.py`.
- Hardening against judge-style abuse (`tests/test_hardening.py`): an empty post is now flagged as a high-priority issue and cannot be approved; double approval and double publishing are rejected; unauthenticated calls return 401; a 200KB post checks without a crash.
- Deploy fix: the Modal image now installs the system libraries OpenCV needs, so OCR works in the deployed build (verified against the live deployment).

## Round 3 hardening pass (late 12 November 2026)

A full line-by-line code audit found and fixed six defects, each with a regression test in
`tests/test_v9.py`:

- **Preview before save.** `POST /api/blueprint` now refuses a rules version that was not
  previewed first (409); the UI's Save button runs the preview automatically.
- **Transactional blueprint saves.** A failed save leaves nothing behind (before, a rejected
  save could be half-committed by a later, unrelated request), and the recovery tasks opened
  by a rule change are committed in the same request (before, a restart could lose them).
- **Input validation.** Bad brand colours, bad claim dates and bad risk values are readable
  400s instead of 500s that broke image checks and the Plan ahead tab.
- **Publish against current rules.** Publishing is refused if the rules changed since
  approval, and the live link must be an http(s) URL.
- **Sessions.** Sign-out now revokes the token (`POST /api/logout`), and the browser stays
  signed in across a refresh.
- **Uploads.** Files are size-capped (20 MB, 413 above) and validated before anything is
  written to disk. DOCX import now uses python-docx (the old path returned raw bytes).
- Multi-statement approve/publish/save paths are serialised with a lock.

## Interface redesign (13 November 2026)

The whole interface was redesigned in a custom editorial style: warm paper canvas, ink type
(Space Grotesk with a Fraunces-italic accent), one signal red reserved for risk and primary
actions, mono small-caps labels, hairline rules instead of pastel cards, and squared plates.
No feature, wording or workflow changed; every screen was re-screenshotted on a running
instance (desktop and mobile).

## Second hardening pass (late 12 November 2026, "360 check")

A second full-angle review found and fixed eight more issues, each with a regression test
in `tests/test_v10.py`:

- **Decision state gate.** "Ask for changes" / "Reject" now only work on in-review content;
  before, they could flip a *published* item back to Draft while the public register still
  showed it live.
- **Dispute gate.** Only open or accepted flags can be disputed; before, disputing an already
  resolved flag quietly re-blocked approval.
- **Defensive approval check.** Approving with no blueprint saved is a readable 400, not a 500.
- **Login throttle.** Eight failed sign-ins for one email pause that email for five minutes (429).
- **Security headers** on every response: X-Content-Type-Options, X-Frame-Options, Referrer-Policy.
- **Text caps.** Post titles (300), post text (500k characters), alt text and comments are capped
  with readable 400s; bad content types are rejected.
- **Empty reasons refused.** Reporting a live post or commenting now requires actual text.
- **Double-click proof UI.** Every button action is guarded while one is already running, so a
  fast double-click can never fire the same mutation twice.

## Roadmap (post-hackathon)

- Real authentication (SSO / per-organisation accounts) replacing the demo logins.
- PostgreSQL and managed object storage for production durability.
- Genuine monitoring of live URLs (fetch and re-check the real page) instead of registered metadata.
- Benchmarked OCR and a benchmarked AI tone layer behind an operator key.
- Accessibility audit and multi-browser testing.
