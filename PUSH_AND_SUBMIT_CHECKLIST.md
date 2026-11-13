# Amrutha: push and submit ReBrand v14

Deadline: Friday, 13 November 2026, 11:59pm IST. One submission for the team, by the leader.

## 1. Push the source

1. Extract this zip. Open the ReBrand_v14_PUSH_READY folder.
2. Use the team's existing ReBrand repository. Copy the extracted folder's CONTENTS into the repository root, not as a nested folder. Keep the repository's existing .git directory. Do not upload the zip itself as the project.
3. Check that README.md, requirements.txt, modal_app.py, app/, static/, tests/ and docs/ are visible at the repository root. Do not add local credentials, .env files, databases or uploads. The supplied .gitignore excludes them.
4. In GitHub Desktop, review the changed files, commit with a message such as "CodeNexus Round 3 final v14", then Push origin. Or use git add / git commit / git push from the existing clone after reviewing the diff. Do not force-push or create a new repository by accident.
5. Open the repository in a signed-out browser and verify judges can read the source. If it is private, follow the organiser's access instructions before submitting.

The app is already deployed. A source push does not require another Modal deploy. Do not run modal_app_test.py or redeploy just to submit.

## 2. Check the judge link

https://akshaykammar31--rebrand-web.us-east.modal.run

Open it in a fresh browser window. Try the one-click judge sign-in. The demo credentials are intentionally public fictional accounts, not personal passwords.

## 3. Finish the submission material

Use docs/SUBMISSION_PACK_DRAFT.md as source material, not as a finished PDF. Replace bracketed placeholders and verify claims before submitting. Its older test counts and hosting caveats have not all been refreshed to v14.

Required material from the organiser's instructions supplied by the team:
- Live link and repository link
- Updated product PDF
- Full feature list and architecture/implementation summary
- Post-Round-2 improvements, including the three commitments
- Testing details and roadmap
- Each member's true role and contribution

Akshay has said his role is backend. Each member must supply their own accurate contribution detail. Do not invent Amrutha's contribution. The optional real Puter flow has not been verified; do not claim it has.

## 4. Submit and save proof

Team leader's form: https://forms.gle/FxhT5Z1NupvGTGSw6

Fill it once for the team, review every link, submit before 11:59pm IST, and save the confirmation screen or receipt. If a submission already exists, inspect that confirmation before creating a duplicate.

## What this bundle is

The v14 FINAL source recovered from the team's Drive archive. Application and deployment source files are unchanged. This handoff only removes compiled Python caches and adds this checklist plus .gitignore. No API keys, personal credentials, local database, uploads or .git history are included. Fictional demo logins remain because the app and tests use them.

Packaging checks: live root HTML and static/app.js matched the source byte-for-byte; health reported version 0.10.0 and the demo story loaded on 13 November 2026 at about 7:39pm IST. These are read-only checks, not a fresh end-to-end test. No repo push, form submission or redeploy was done for this handoff.
