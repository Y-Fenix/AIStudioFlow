# Department-Owned UI and Executor Slots Implementation Plan

> **For agentic workers:** Implement inline in this task. Preserve the repository rule against Git pull/commit operations.

**Goal:** Let department leads own a small frontend module and trusted Python executor while keeping identity, authorization, persistence, model credentials, and approval in the shared StudioFlow shell.

**Architecture:** Department manifests declare a same-origin `ui.js` entry. The server only serves that file from a known department directory, and the shell lazily imports it for that department's home and node workspace. Modules expose optional `renderHome(context)` and `renderWorkspace(context)` functions that return markup; shared shell permissions and actions remain authoritative. Existing `adapter.py` loading remains the backend entry point and imported Skills never become executable code.

**Tech Stack:** Python standard library HTTP server, JSON manifests, vanilla JavaScript ES modules, unittest.

---

### Task 1: Declare and validate frontend module entries

**Files:**
- Modify: `server/studio_catalog.py`
- Modify: `departments/*/manifest.json`
- Test: `tests/test_team_platform.py`

- [x] Add optional manifest field `frontend: {"entry":"ui.js"}` and reject any other entry/path or malformed value.
- [x] Add the field to each of the five department manifests; keep testing's existing six-node workflow and expose a department-owned summary panel.
- [x] Test valid entries and reject traversal, absolute paths, and unsupported entry names.
- [x] Run `python3 -m unittest tests.test_team_platform.DepartmentManifestTests`.

### Task 2: Serve only declared same-origin department UI modules

**Files:**
- Modify: `server/app.py`
- Test: `tests/test_team_platform.py`

- [x] Resolve `/departments/<known-id>/ui.js` using the validated catalog and module root; return JavaScript with `Cache-Control: no-store`.
- [x] Return 404 for unknown departments, undeclared modules, extra path segments, or traversal attempts.
- [x] Test the allow-list and ensure no arbitrary department files can be read through the static route.
- [x] Run focused manifest and route tests.

### Task 3: Add shell-owned render slots and department examples

**Files:**
- Modify: `web/studio.js`
- Create: `departments/product/ui.js`
- Create: `departments/design/ui.js`
- Create: `departments/development/ui.js`
- Create: `departments/growth/ui.js`
- Modify: `docs/departments/README.md`
- Test: `tests/test_team_platform.py`

- [x] Lazy-load a department's declared ES module and cache it by stable department ID; a failed module load falls back to the public generic renderer.
- [x] Pass only the current department/node, project/studio labels, workspace summary, and safe HTML helper to optional `renderHome(context)` / `renderWorkspace(context)` hooks.
- [x] Preserve shell-owned Skill import/export, saving, execution authorization, audit, and human approval controls outside the extension slots.
- [x] Add one focused example module per non-testing department that identifies its node deliverable and clearly marks unavailable external tools as not connected; do not fabricate generated work.
- [x] Document module ownership, hook signatures, same-origin trust boundary, backend `adapter.py` contract, and the prohibition on treating Skills or uploaded content as executable code.
- [x] Test static module allowlist and safe render context with Node's built-in test runner; run `node --check` for shell and modules, and run the full Python test suite.

## Scope check

This plan only delivers the department-owned extension boundary. It does not claim that product research, competitor binary analysis, image generation, development code editing, Feishu OAuth, or general Feishu/GM connectors are connected; those require separate department-specific adapters and real service verification.
