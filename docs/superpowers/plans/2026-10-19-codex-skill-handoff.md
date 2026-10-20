# Codex Skill 本机交接 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user hand the current node Skill to Codex on their own Mac through a one-use authenticated handoff, without automatically sending the prompt.

**Architecture:** The authenticated StudioFlow server creates a short-lived, single-use capability tied to the current actor and node. A per-Mac URL-scheme bridge redeems it over HTTPS, places the install prompt on the clipboard, launches Codex and pastes into its composer; the user remains responsible for pressing Enter and approving Codex file writes.

**Tech Stack:** Python stdlib HTTP/SQLite, browser JavaScript, macOS Swift/AppKit and AppleScript UI automation, unittest, Node test runner.

---

## Files and responsibilities

- `server/core/schema.py`: additive one-time handoff table migration.
- `server/core/skill_handoff.py`: ticket creation, permission/scope checks, prompt construction, atomic single-use redemption and expiry cleanup.
- `server/core/routes.py`: authenticated create/redeem endpoints. Create endpoint rechecks `skill.export`; redemption uses only the capability ticket and refuses inactive actors.
- `web/studio.js`: add “在 Codex 使用” before Skill import/export; request ticket and invoke its custom URL; show actionable fallback if the bridge is unavailable.
- `web/department-ui-contract.js`: expose capability only when node-level Skill export is allowed (if the existing contract does not already expose it).
- `tests/test_skill_handoff.py`: authorization, node isolation, one-use, expiry, account status and prompt integrity tests.
- `tests/department-home-ui.test.js`: button ordering and request behavior contract.
- `deploy/mac/codex-bridge/Info.plist`, `main.swift`, and `README.md`: per-user URL-scheme app, HTTPS ticket redemption, clipboard, launch/paste behavior and setup/privacy requirements.
- `docs/mac-team-deployment.md`: document per-client bridge installation and Accessibility permission separately from server setup.

## Task 1: Build the ticket lifecycle

- [x] Add a test proving `skill.export` denial prevents ticket creation.
- [x] Add a test proving a valid ticket returns only its bound node's current Skill and cannot be consumed twice.
- [x] Add expiry, inactive actor, permission revocation and invalid project/node checks.
- [x] Run `python3 -m unittest tests.test_skill_handoff` and verify those tests fail before implementation.
- [x] Add the SQLite table with token hash, actor, studio, project, node, prompt, expiry and consumed timestamp.
- [x] Implement ticket creation after rechecking user, project and node-level Skill export permission.
- [x] Implement atomic redemption in the same transaction and recheck the creator's current active status and permissions; never log token or prompt.
- [x] Run `python3 -m unittest tests.test_skill_handoff` and verify all lifecycle tests pass.

## Task 2: Add authenticated HTTP endpoints

- [x] Add an HTTP test that ticket creation requires an active authenticated user and exact-node `skill.export`, and redemption rejects replay.
- [x] Route department-workspace and six-node testing Skill handoffs through the shared permission layer.
- [x] Route POST `/api/codex-handoff/redeem` using a short random capability; do not require the browser session cookie on the native client.
- [x] Use the app's bounded JSON request and no-store response path; bind creation and redemption to the configured HTTPS or local loopback origin.
- [x] Run team HTTP and handoff tests.

## Task 3: Add the Skill action in the shell

- [x] Add a failing UI contract test that the action appears immediately before Skill import/export and references the current node.
- [x] Implement `在 Codex 使用` only when node-level Skill export is authorized.
- [x] On click, create a ticket, then navigate to the returned `studioflow-codex://` URI. Do not place Skill content in the URI or call Enter.
- [x] Show a manual clipboard/fallback message when the native handler is missing or refuses launch.
- [x] Run `node --test tests/department-home-ui.test.js tests/department-ui-contract.test.js` and `node --check web/studio.js`.

## Task 4: Build the per-Mac bridge

- [x] Add a local validation test for scheme parsing, accepted origins, payload size limits and one-time ticket handling where feasible without automating Codex UI. Swift policy/payload tests and Python ticket lifecycle tests cover these boundaries; native UI remains unverified.
- [x] Create a Swift AppKit URL handler for `studioflow-codex://handoff` and reject any other scheme or malformed ticket.
- [x] Fetch ticket data from the origin carried by the URL using HTTPS (allow HTTP only for `127.0.0.1`, `localhost` and `::1`).
- [x] Limit the prompt to 500,000 UTF-8 bytes and response to 600,000 bytes during reception; clear pasteboard data before use.
- [x] Resolve the installed `com.openai.codex` application by bundle ID and launch it with NSWorkspace; locate its actual process ID and check the focused element role before attempting paste.
- [x] Never synthesize Return/Enter. If Codex cannot be focused or Accessibility permission is missing, leave the prompt copied and show the next manual step.
- [x] Provide an unsigned per-user build guide that registers the URL handler without administrator privileges.

## Task 5: Final verification and documentation

- [x] Document that the bridge is installed on each client Mac, not only the server, and that macOS may prompt for Accessibility permission.
- [x] Run `python3 -m unittest discover -s tests`, `node --test tests/*.test.js`, Python/JavaScript syntax checks, and Swift type/build checks.
- [x] Verify latest assets are served from the local preview.
- [ ] Test real Codex UI automation on a Mac with the actual Codex app installed; status remains explicitly unverified.

## Self-review

- Covers button placement, per-user local installation, secure transfer, access control, one-use behavior, clipboard insertion and the user's explicit Enter decision.
- Does not write Skills directly from the StudioFlow server, auto-send prompts, alter Codex approvals, or claim a successful Codex install before native-app verification.
- Existing repo instruction prohibits Git pull/commit; plan execution must not commit despite generic plan templates elsewhere.

## Latest local verification — 2026-10-19

以下 260 / 17 项是早期检查记录。当前完整验收见 [`../../studio-platform-acceptance.md`](../../studio-platform-acceptance.md)：280 项 Python、22 项 Node 通过；本机首次协议启动及兑换已验收，真实粘贴受系统辅助功能权限阻挡。

- `python3 -m unittest discover -s tests`: 260 tests passed. The queue recovery test intentionally logs its injected temporary database I/O error; the suite exits 0.
- `node --test tests/*.test.js`: 17 tests passed.
- Swift URL/payload policy executable passed; AppKit bridge compiled successfully on this Mac. No application was installed or launched, and no clipboard/UI operation was performed during these checks.
- Python/JavaScript syntax checks and `Info.plist` validation passed.
- Server-origin regression test first demonstrated acceptance of an unwanted path/query/fragment, then passed after aligning validation with the native bridge. Swift payload checks cover malformed JSON, empty/non-string text, UTF-8 size limits and refusal to retain an oversized chunk.
- No real multi-enterprise Feishu login, target-team deployment or Codex native UI acceptance is claimed by these checks.

## Client packaging follow-up

- `tools/build_codex_bridge.py` creates an architecture-specific, ad-hoc signed application ZIP plus SHA-256 under ignored `dist/codex-bridge/`. It sets the binary's actual minimum OS to macOS 13 instead of relying only on Info.plist.
- Package integration checks inspect archive contents, executable permissions, URL scheme and Mach-O deployment target. Installation/launch/clipboard operations are not performed by this test.
- The compiled bridge's `--check-target` found `/Applications/ChatGPT.app` on this Mac; its bundle ID is `com.openai.codex`. The old literal app/process-name assumption was replaced. Native launch/focus/paste acceptance remains pending.
