# ReBrand - Round 3 submission pack (DRAFT, not submitted)

Status: updated 12 Nov 2026 after the live deploy. The app is deployed and verified on the team's own Modal account. Items in [square brackets] are still for the team to fill. Round 3 is judged by Inkloom; rule 21 on the event page says Round 3 is measured against the three improvements named in Round 2.

## 1. Completed-improvements list

The three commitments come from Section 5 of the Round 2 PDF.

| # | Commitment (Round 2 wording) | Built in Round 3 | How it was checked |
|---|---|---|---|
| 1 | Guideline-change impact preview: before saving a new guideline version, show which registered posts would newly fail, which rules cause it, and the recovery workload | `POST /api/blueprint/preview` and a "Preview the impact first" button in Brand rules. Re-runs every live post against the proposed rules without saving. Shows newly failing posts, the rule behind each, severity, estimated number of fix tasks, and posts that would be cleared. Manager or reviewer only. | Automated test: preview reports 1 newly failing post for a new banned term, saves nothing (version unchanged, no recovery task), a creator gets 403, an unchanged blueprint shows 0. Screen checked in headless Chrome. |
| 2 | Claim expiry and renewal: scheduled checks for approaching and reached expiry, owner notifications, renewal review, recheck of affected posts | `GET /api/claims/expiry` lists expired and expiring claims with the live posts using them. A scan notifies the post owner, and opens a recovery task for live posts using an expired claim. The scan runs on demand and on a timer inside the server (`REBRAND_SCAN_HOURS`, set to 24 in render.yaml), and does not repeat the same notice on the same day. Renewal (`POST /api/claims/renew`) needs a manager or reviewer and a written evidence note, then saves a new rules version and rechecks live posts. "Plan ahead" tab in the UI. | Automated tests: expiring and expired statuses, role checks (creator gets 403), renewal rejected without evidence, renewal clears the status, a second scan the same day adds no duplicate notice. Timer verified once by running the server with a short interval. |
| 3 | Dispute learning: aggregate dispute reasons and reviewer decisions, propose clearer guideline wording for human approval | `GET /api/guideline-suggestions` groups disputes by rule, shows the reasons, the dispute rate, reviewer change requests, and drafts clarification wording. A manager or reviewer can edit and approve it; only then `POST /api/guideline-suggestions/approve` saves a new rules version. | Automated test: two disputes on the same rule give a "strong" suggestion with draft status, creator cannot approve, approval creates a new version containing the clarification. |

The wording drafts come from a template that quotes the real dispute reasons. They are not written by an AI model.

## 2. Round 2 bugs and gaps fixed

- Demo data disappeared after a redeploy (stated as a limitation in Round 2). Fix: the server can seed itself and reload a fictional demo story on every start (`REBRAND_AUTOSEED`, `REBRAND_DEMO_STORY`). This avoids needing a paid disk. Real user data on the free host is still not durable.
- Image text was never read (OCR was deferred in Round 2). Fix: optional RapidOCR (PaddleOCR models on ONNX Runtime, CPU only) reads the words inside an image post and runs them through the same banned-term and claim rules. Evidence is marked "Text read from the image (OCR)". It is optional: without the package, image checks run as before. Tested on one synthetic ad image only (it found banned words); accuracy on real posts, blurry or stylised text is not measured, and it can drop spaces in large headlines.
- Sessions never expired. Fix: sessions older than 7 days are rejected.
- Judges had no quick path through the product. Added one-click Creator and Manager sign-in, a demo story with 3 live posts, 1 fix task, a claim expiring in 12 days and 2 disputes, and a "Fill in a sample off-brand post" button.
- Added in the final build (12 Nov): a "What's new in Round 3" tab that maps each promised improvement to where a judge can try it, an "Activity" tab showing the audit trail (who approved what, when), and hardening against judge-style abuse: an empty post is flagged high-priority and cannot be approved, double approval and double publishing are rejected, unauthenticated calls get 401, and a 200KB post checks without a crash.

## 3. Optional extra: AI tone review through Puter

Button "Optional: AI tone review (Puter)" in Review. It runs in the browser on the signed-in person's own Puter account, so the team holds no API key. The server treats the model output as untrusted: findings whose evidence is not quoted from the draft are dropped, findings without a quoted guideline clause are saved as Uncertain, all are medium severity and labelled as AI, and a human still decides. The core product works without it.
Status: the server side is tested. The browser side was tested only with a stand-in for Puter, not the real service, and Puter's free allowance was not verified. [Team: test once with a real Puter account before claiming this works.]

## 4. Technical details

- Stack: Python 3, FastAPI and Uvicorn, SQLite, vanilla JavaScript with Tailwind (CDN), Pillow, pypdf. No paid services.
- Rule engine: deterministic terminology, promotional-claim, expiry, heading, reading-level and image checks. Every finding carries evidence, the guideline clause and a suggested fix.
- Governance: server-enforced roles, a fresh-check requirement before approval, a published register tied to the rules version, recovery tracking with human approval at each step, and an audit trail.
- New in Round 3: impact preview (read-only re-evaluation against a candidate rules snapshot), expiry scanner with timer and de-duplicated notifications, renewal as a new rules version, dispute aggregation, notifications table, demo story loader, optional Puter AI intake.
- Deployment: Modal (modal.com), one always-warm container (no cold start for judges), 1 CPU / 1 GiB, data on a persistent Modal Volume, auto-seed and demo story on start. `modal_app.py` in the repo is the deploy file; `render.yaml` remains as a free fallback. Live URL: https://akshaykammar31--rebrand-web.us-east.modal.run
- Source: [fill in: repository link after the team pushes]. The Round 2 code base was extended; unchanged areas are the Round 2 work.

## 5. Testing notes

Suites run 12 Nov 2026 against the deployed Modal build (a separate throwaway copy of the app, so judge-visible demo data was not touched), each against a freshly seeded database.

- `tests/test_e2e.py` (Round 2, unchanged): 32 checks pass.
- `tests/test_round3.py`: 30 passing calls covering features 1 to 3, all pass.
- `tests/test_demo_story.py`: 14 passing calls covering the demo story, the scan de-duplication and the AI-tone intake rules.
- `tests/test_ocr.py`: a synthetic image with banned words is uploaded and the OCR findings come back (TERM_BANNED, CLAIM_UNSUPPORTED). A single-image test, not an accuracy benchmark.
- `tests/test_safety.py`: expired claims rejected, current claims allowed.
- Live URL verified in a desktop Chrome browser on 12 Nov: sign-in with the one-click judge buttons, the demo story (3 live posts, 1 open fix task, a claim expiring in 12 days, disputes), the Review queue, Live posts, Posts to fix and the Plan ahead tab all render and respond.
- `tests/test_activity.py`: the audit trail records who did what, newest first.
- `tests/test_hardening.py`: empty content blocked from approval, double approve/publish rejected, auth walls, 200KB input.
- `tests/test_v9.py` (audit hardening, 13 checks): failed rules save leaves nothing behind; recovery tasks from a rule change are committed; invalid colours/dates rejected 400; saving rules without an impact preview refused 409; publishing after a rules change refused; logout revokes the session; oversize upload 413; invalid image 400; DOCX import; non-http live link refused.
- `tests/test_v10.py` (second pass, 8 checks): decisions only on in-review content; resolved flags cannot be disputed; security headers; login throttle 429; title/text caps; empty report reasons and comments refused; bad content type 400.
- Simple load check on 9 Nov: 100 concurrent requests to the home page, 0 failures, median 0.83 s, worst 1.3 s (measured from a cloud server; Indian judges may see different latency).
- OCR fix during deploy: the first deployed image could not import the OCR library (missing system libraries for OpenCV). Fixed by adding system packages to the deploy image; the OCR test above passes on the deployed build.
Not tested: OCR accuracy beyond one synthetic image, real Puter, formal load or security testing, accessibility audit, browsers other than Chrome.

## 6. Roadmap after the hackathon

- Real authentication (SSO, per-organisation accounts) replacing demo logins.
- PostgreSQL and managed object storage for production durability.
- Genuine monitoring of live URLs (fetch and re-check the real page) instead of registered metadata.
- Benchmarked OCR and an AI tone layer behind an operator key.
- Accessibility audit and multi-browser testing.

## 7. Changes versus the original plan

- The three commitments are kept as named in Round 2. Impact preview and renewal are as described. Dispute learning drafts wording from a template and the dispute reasons, not from a language model.
- Expiry checks run on a timer inside the web server. That timer stops if the host sleeps (free hosts do), so on-demand scan stays available.
- OCR was added after Round 2 as an optional component. Image checks otherwise use hashes, palette and supplied descriptions.
- No change to the rule that humans approve every publication and correction. ReBrand still never posts to external channels.

## 8. Known limits and risks

- Authentication is demo-grade (fixed demo accounts), no SSO, no security audit.
- OCR can misread text or drop spaces, so its findings go to a human like every other check.
- Free hosting may sleep or wipe data. The demo story reloads, user-entered data does not persist.
- The in-process timer and request handlers share one SQLite connection. Fine for a demo, not a production design.
- Similarity and number differences between posts are advisory, not proof of a factual contradiction.
- AI assistance was used for code, tests and documents. [Team: disclose this in the form as the rules require.]

## 9. Team contributions (TO BE WRITTEN BY EACH MEMBER)

Per the organisers' Round 3 message (13 November), ONE submission is filed for the whole
team by the team leader (Amrutha). The form asks for each member's role and contribution.
This pack does not assign credit.
- Amrutha K: [role] [what she built]
- Akshay Kammar: [role] [what he built]
