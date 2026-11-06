# ReBrand - AI-Powered Brand Damage Recovery System

CodeNexus India 2026, Round 2 build. Problem statement by Inkloom AI: intelligent
brand-governance platform. Team: RASHI INNOVATORS (Amrutha K - team leader; Akshay Kammar).

ReBrand checks content **before publication** against an organisation's own brand
blueprint (guidelines, terminology, approved claims, assets, palette, accessibility
rules), explains every issue with the guideline behind it, and suggests corrections
that preserve the creator's intent. After publication it keeps a register of live
items and **recovers damage**: when a guideline changes or a claim expires, affected
live items are re-checked, damaged ones become tracked recovery tasks, and every
corrective action requires human approval before closure.

## Interface (redesigned 6 November — simple, calm, human)

The backend and API are unchanged; only the words, colours and layout changed.
No feature was added or removed in this redesign.

- **One job per screen.** Sign-in opens straight on "Write a new post". Every
  screen has one main button, in plain words ("Check my post", "Approve",
  "Mark as published"). Sections are named for what they are: Brand rules,
  New post, Review, Live posts, Posts to fix, Simple numbers.
- **Plain words, not jargon.** Issues say "Stop — fix this first",
  "Check this" or "Small fix" instead of severity codes, and every flag says
  what was found, why it matters, and how to fix it. Empty screens explain
  what will appear there, instead of showing a blank list.
- **Colours chosen for stressed people doing careful work.** Brand and social
  teams check posts under time pressure, so the interface is calm first:
  warm paper background (#F6F1E7, like a printed page, easy on the eyes),
  deep green (#17573F) for trust, safety and "go" — the colour of approval —
  warm amber (#B7791F) for "look at this", and a muted brick red (#B3402E)
  used only for "stop". No blue/purple gradients, no glass panels, no
  generic AI look. Headings are a warm serif (Fraunces); body text is a
  plain sans-serif. Green means safe, amber means check, red means stop —
  the same meaning everywhere in the app, so a new user learns it once.

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
python tests/test_e2e.py # 32 checks: full workflow, both content types
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

- OCR for text inside images is planned (Tesseract) but not wired; image text
  checks currently apply to supplied alt text and metadata only.
- AI tone check requires the operator to supply a model key via environment
  variables; without it, tone review is routed to humans as Uncertain.
- Auth is demo-grade role-based access, not SSO.


## Round 2 safety fixes (6 November)
- Scans and approvals are tied to exact content and blueprint versions; content changes invalidate scans.
- Accepting/disputing a high-priority finding cannot bypass approval; fix and re-scan.
- Expired approved claims are flagged at initial submission.
- Recovery correction requires a human's written confirmation of the external change; closure remains reviewer-only with recheck. This is **manual confirmation**, not automated verification of a live website.
- Schema upgrades are applied to existing SQLite databases.
- The uploaded source bundle did **not** contain the original `static/app.js`; this package includes a replacement JavaScript frontend. Browser walkthrough is still required before claiming full UI verification.

## Previous Post Memory Check (Round 2 small addition)
On **Submit content**, choose **Compare with previous posts**. The feature compares the draft with up to 150 published items in the same workspace, shows up to three related posts with dates, and highlights possible numerical differences. It does not scrape external sites or claim a previous figure is false; a human must verify. This is an advisory check, not an approval bypass.

## Final Round 2 build
- Includes the Previous Post Memory Check on the Submit content screen.
- Fresh-install verification: 32/32 end-to-end API checks, expired-claim safety check, and JavaScript syntax check passed.
- This is a local runnable build; public hosting and full browser interactions have not been independently verified.
- For production hosting, configure persistent storage and production authentication; the seeded accounts are demo-only.
