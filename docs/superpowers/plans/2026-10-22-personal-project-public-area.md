# Personal Workspaces and Project Public Area Implementation Plan

> **For agentic workers:** Execute inline with executing-plans. User already approved the design; do not ask for another execution choice. No Git mutation or Figma changes.

**Goal:** Keep personal execution local and allow reviewed, selected snapshots to be published to an independently authenticated central project service.

**Architecture:** An explicit personal runtime and an independent public runtime share existing account/project authorization components. A local connector maps project IDs and retains only its device session. Public storage accepts immutable, versioned data packages and never invokes model or execution queues.

**Tech Stack:** Python standard library HTTP/SQLite, existing authentication/policy, plain JavaScript/CSS, unittest and Node tests.

---

## 1. Server boundary and immutable publication protocol

Files: `server/core/public_area/{schema,packages,service,routes}.py`, `server/app.py`, `server/core/permissions.py`, `tests/test_public_area.py`.

- [x] Write tests using isolated Stores and real identity contexts: ungranted member cannot publish; author is server-derived; malformed attachments and private absolute paths rejected/redacted; retries return one revision; concurrent revisions conflict; withdrawal hides all revisions; revoked grant blocks commit.
- [x] Verify regressions fail before their fixes. Preserved red evidence covers runtime discovery (`ui.readRuntime is not a function`) and personal default database isolation (expected personal DB absent); no initial missing-module result is claimed.
- [x] Add separate additive public tables for project versions, publications, immutable revisions, operation IDs, temporary uploads and audit. Validate JSON-only allowlisted fields, 2 MB package limit, 700 KB individual attachments, exact hashes, supported text/JSON/PNG/JPEG/PDF/DOCX/XLSX; never unpack or execute uploads.
- [x] Enforce explicit `publication` resource grants with existing project membership, stable department/node and optional Skill scope checks. Fetch each revision and attachment only after latest authorization and withdrawal checks.
- [x] Stage a complete package privately, then commit atomically using operation ID and expected revision. Delete abandoned stages after 24 hours. Persist public-event notifications independently of upload success.
- [x] Re-run protocol tests.

## 2. Independent deployment and local connector

Files: `server/core/public_area/{client,local}.py`, `server/app.py`, `tests/test_public_area_http.py`, `tests/test_public_area_client.py`.

- [x] HTTP tests start personal/public servers against three temporary DBs. Patch worker constructors to raise in public mode; verify no constructors invoked. Authenticate with real password accounts and test forbidden model/repository/task routes.
- [x] Implement `--mode team|personal|public`; default team retains compatibility; personal requires loopback and suppresses team webhook; public permits only identity, organization administration and public routes, starts no execution workers. Public CLI uses a different default DB.
- [x] Connector saves server URL and session privately per local identity, prohibits URL credentials/redirects and requires explicit restricted LAN HTTP. Login/register use remote auth, server determines author. Logout revokes remote session.
- [x] Explicitly bind local project to remote studio/project/version IDs after checking both ends; server switch clears mapping. Source snapshot records local revision/digest; final publish refuses changed source. Network ambiguity retains same operation ID for status lookup and retries, never auto-publishes.
- [x] Export node deliverables, selected QA artifacts, opt-in requirements/Skill and workflow configuration through authorized platform services. Never serialize full task or DB. Imported public data remains inert and is saved to a separate local copy before user chooses further use.
- [x] Run `python3 -m unittest tests.test_public_area_http tests.test_public_area_client -v`.

## 3. Personal/public interface

Files: `web/public-area.js`, `web/public-area.css`, `web/studio.js`, `web/index.html`, `web/app.js`, `tests/public-area.test.js`, `tests/browser/public-area.cjs`.

- [x] Add UI tests for escaped content, paging/filtering, explicit confirmation, disconnected status and no automatically checked source/Skill options.
- [x] Add project public navigation and contextual publish actions. Connection dialog supports URL, explicit LAN HTTP, login/register/logout, remote project/version selection and binding. Preview uses frozen selected snapshot and shows local/unuploaded, pending verification or published accurately.
- [x] Public list filters by version/department/node/author/type, supports revision details, authorized attachment download, withdraw and inert copy to local area. Independent public server page offers login, project/version administration and permissions through the existing UI shell, without model/run links.
- [x] Verify modal backdrop/Escape, busy buttons, failures preserve draft and selected inputs, no scroll jumps or double submissions.
- [x] Run Node tests and actual browser workflow across isolated HTTP servers.

## 4. Compatibility, documentation and verification

Files: `README.md`, `docs/departments/README.md`, `docs/personal-public-area.md`, `docs/personal-public-area-acceptance.md`.

- [x] Read-only record live case count and artifact hashes before/after; use temporary directories for all publication tests. Never upload real documents or send real webhooks during tests.
- [x] Run full Python and Node suites; fix regressions attributable to changes. Inspect changed lines for credential exposure, authorization bypass and private-path leakage.
- [x] Document separate launch commands, central account approval and publication permissions, HTTPS/LAN setup, credential/session expiry, explicit upload and recovery. Record automated and real cross-machine verification separately.
- [x] Preserve the active team server on 8766: its real execution job is still progressing, so do not restart it. Start an independent personal instance on 8767 with `data/personal/platform.sqlite`, verify both login pages in Chrome and open the personal page. A legacy runtime discovery fallback preserves old-service loading; do not publish real content or share its DB.
