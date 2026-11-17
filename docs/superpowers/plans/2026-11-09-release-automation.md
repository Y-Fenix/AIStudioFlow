# Release automation implementation plan

**Goal:** One workbench start coordinates project-local skills, source review, available deterministic checks, resumable execution and evidence-based reports; external publication stays manual.

**Architecture:** Extend testing-owned compatibility entries and QA modules. Reuse public job, permission and checkpoint contracts. Record missing platform contracts before integration; do not modify platform-owned files without maintainer review. No Git operations or global skill edits.

**Tech Stack:** Python unittest, existing Python server and vanilla JavaScript UI, Playwright browser acceptance.

- [x] Copy required skills into .agents/skills and retain original hashes.
- [x] Reproduce removed-source crash and repeated source reads with tests/test_QA_source_cache.py.
- [x] Fix missing-source reporting and bounded thread-safe source cache with live metadata validation in server/static_review.py. Targeted 33 tests passed.
- [x] Define shared project/repository/baseline/check/result contracts and local skill dependency resolution.
- [x] Add module evidence sharing without weakening independent case assertion validation.
- [x] Add four-repository deterministic checks and business review integration, preserving unsupported and unreviewed scope.
- [x] Add a local resumable coordinator; public queue/start/resume integration remains a documented platform contract gap.
- [x] Add a consolidated report with severity, evidence status and manual authorization gates.
- [ ] Verify real read-only repository/tool smoke separately from fixture transport tests.
- [x] Run required Python and JavaScript regressions, department boundary checks and desktop/mobile browser inspection.
- [ ] Audit objective against actual implementation and acceptance evidence before marking complete.

## Validation commands

`python3 -m unittest tests.test_QA_source_cache tests.test_static_review tests.test_QA_review_concurrency tests.test_QA_review_checkpoints`

`python3 tools/check_department_boundaries.py --department testing`

`python3 -m unittest tests.test_case_validation tests.test_generation tests.test_static_review tests.test_execution tests.test_attribution tests.test_triage tests.test_bugs tests.test_regression tests.test_node_settings tests.test_node_reset tests.test_workflow_e2e`

`node --test tests/*.test.js`

`node --test tests/department-ui-contract.test.js`

`node tests/browser/workflow-insights.cjs`

The local source cache improves repeated filesystem reads only. It does not yet reduce model calls or prove full workflow integration. Fixture tests do not establish real payment, advertising, analytics delivery or installation behavior.
