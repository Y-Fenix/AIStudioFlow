#!/usr/bin/env python3
"""Execution gaps stay with the agent; external facts cannot conceal local work."""
from copy import deepcopy
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import audit_completion as gate
import merge_domain_audits as merge


def report():
    cases = [{"id": f"c{i}", "dimension": dim, "verdict": "未见问题",
              "trace": [{"path": "Fixture.cs", "line": 1}]} for i, dim in enumerate(gate.DIMENSIONS)]
    owner = {"id": "feature-1", "name": "测试功能", "source_paths": ["Fixture.cs"],
             "display": {"category": "系统"}, "gaps": [],
             "static_audit": {"status": "已完成", "cases": cases, "depth": {
                 "branches": [{"id": "branch-1", "evidence": [{"path": "Fixture.cs", "line": 1}]}],
                 "coverage": [{"dimension": dim, "status": "已闭合"} for dim in gate.DIMENSIONS]}}}
    return {"features": [owner], "findings": [], "configuration_groups": [],
            "scope_control": {"mode": "targeted", "reason": "合成单功能门禁测试，非项目全量", "feature_ids": ["feature-1"]},
            "level_audit": {"pipeline_version": 2, **{stage: {
                "status": "检查完成未见问题", "total": 1, "checked": 1,
            } for stage in ("layout", "solvability", "visual")}}}


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.evidence = self.root / "evidence"
        saved = self.evidence / "sources/Fixture.cs.txt"
        saved.parent.mkdir(parents=True)
        saved.write_text("production source\n")
        (self.root / "Fixture.cs").write_bytes(saved.read_bytes())

    def check(self, data):
        return gate.completion(data, self.root, self.evidence)

    def test_completed_local_work_has_no_continuation(self):
        result = self.check(report())
        self.assertTrue(result["ready_for_final"])
        self.assertEqual(result["summary"]["complete_review"], 1)

    def test_inventory_only_creates_one_agent_task_not_seven_human_tasks(self):
        data = report()
        data["features"][0]["static_audit"] = {"status": "未完成", "cases": []}
        result = self.check(data)
        self.assertFalse(result["ready_for_final"])
        self.assertEqual(result["summary"]["missing_dossier"], 1)
        self.assertEqual(len(result["tasks"]), 1)
        self.assertEqual(set(result["tasks"][0]["dimensions"]), set(gate.DIMENSIONS))

    def test_free_form_gap_cannot_hide_behind_green_cases(self):
        data = report()
        data["features"][0]["gaps"] = ["未追到奖励落盘消费者"]
        result = self.check(data)
        self.assertFalse(result["ready_for_final"])
        self.assertIn("未追到奖励落盘消费者", result["tasks"][0]["reasons"])

    def test_external_fact_does_not_block_completed_client_analysis(self):
        data = report()
        data["features"][0]["external_checks"] = [{"id": "server-contract"}]
        result = self.check(data)
        self.assertTrue(result["ready_for_final"])
        self.assertEqual(result["summary"]["external_facts_out_of_scope"], 1)

    def test_external_label_cannot_remove_unchecked_local_case(self):
        data = report()
        data["features"][0]["external_checks"] = [{"id": "server-contract"}]
        data["features"][0]["static_audit"]["cases"][0].update(verdict="未检查", reason="尚未查旧响应处理")
        result = self.check(data)
        self.assertFalse(result["ready_for_final"])
        self.assertIn("尚未查旧响应处理", result["tasks"][0]["reasons"])

    def test_same_head_working_tree_change_requires_recheck_and_preserves_snapshot(self):
        saved = self.evidence / "sources/Fixture.cs.txt"
        before = saved.read_bytes()
        (self.root / "Fixture.cs").write_text("changed production source\n")
        result = self.check(report())
        self.assertFalse(result["ready_for_final"])
        self.assertEqual(result["tasks"][0]["changed_sources"], ["Fixture.cs"])
        self.assertEqual(saved.read_bytes(), before)

    def test_source_drift_flag_cannot_be_cleared_by_matching_snapshots(self):
        data = report()
        data["features"][0]["source_drift"] = ["Fixture.cs"]
        self.assertFalse(self.check(data)["ready_for_final"])

    def test_current_scenario_recheck_resolves_only_reviewed_source_drift(self):
        owner = {"source_drift": ["Fixture.cs", "Other.cs"]}
        detail = {"checks": [{"case_id": "c1", "evidence": [{"path": "Fixture.cs"}]}],
                  "source_rechecks": [{"path": "Fixture.cs", "case_ids": ["c1"],
                                       "conclusion": "已追查变更条件和最终消费者"}]}
        merge.apply_source_rechecks(owner, detail, {"source_hashes": {"Fixture.cs": "hash"}})
        self.assertEqual(owner["source_drift"], ["Other.cs"])

    def test_unrelated_case_cannot_clear_changed_source(self):
        owner = {"source_drift": ["Fixture.cs"]}
        detail = {"checks": [{"case_id": "c1", "evidence": [{"path": "Other.cs"}]}],
                  "source_rechecks": [{"path": "Fixture.cs", "case_ids": ["c1"], "conclusion": "已查"}]}
        with self.assertRaisesRegex(ValueError, "没有引用变更路径"):
            merge.apply_source_rechecks(owner, detail, {"source_hashes": {"Fixture.cs": "hash"}})

    def test_configuration_gap_is_also_returned_to_agent(self):
        data = report()
        group = deepcopy(data["features"][0])
        group["id"] = "config-1"
        group["display"] = {"category": "配置"}
        group["static_audit"]["status"] = "未完成"
        data["configuration_groups"] = [group]
        result = self.check(data)
        self.assertEqual(result["tasks"][0]["agent"], "配置与存档")

    def test_solver_budget_unknown_is_not_a_bug_or_a_pass(self):
        data = report()
        data["level_audit"]["solvability"].update(status="检查未完成", checked=0, summary="预算内未定")
        result = self.check(data)
        self.assertFalse(result["ready_for_final"])
        self.assertEqual(result["tasks"][0]["id"], "level:solvability")
        self.assertEqual(result["summary"]["confirmed_bug_count"], 0)

    def test_empty_inventory_cannot_complete(self):
        data = report()
        data["features"] = []
        self.assertFalse(self.check(data)["ready_for_final"])

    def test_small_batches_cover_each_task_once(self):
        data = report()
        data["features"] = [{**deepcopy(data["features"][0]), "id": f"f{i}", "gaps": ["待续查"]} for i in range(8)]
        data["scope_control"]["feature_ids"] = [f["id"] for f in data["features"]]
        result = self.check(data)
        dispatched = [task for batch in result["batches"] for task in batch["task_ids"]]
        self.assertEqual(len(dispatched), len(set(dispatched)))
        self.assertEqual(set(dispatched), {task["id"] for task in result["tasks"]})
        self.assertTrue(all(len(batch["task_ids"]) <= 3 for batch in result["batches"]))

    def test_confirmed_count_deduplicates_root_cause_and_excludes_risk(self):
        data = report()
        data["findings"] = [{"id": "bug1", "kind": "静态缺陷已证"},
                            {"id": "bug1", "kind": "静态缺陷已证"},
                            {"id": "risk1", "kind": "条件风险"}]
        self.assertEqual(self.check(data)["summary"]["confirmed_bug_count"], 1)

    def test_dossier_source_hash_must_match_even_with_same_head(self):
        obj = {"baseline": {"head": "current", "source_hashes": {
            "Fixture.cs": hashlib.sha256(b"production source\n").hexdigest()}},
               "features": [{"source_paths": ["Fixture.cs"]}]}
        path = self.root / "dossier.json"
        path.write_text(json.dumps(obj))
        with patch.object(merge.subprocess, "check_output", return_value="current\n"):
            merge.validate_baselines([path], self.root)
            (self.root / "Fixture.cs").write_text("changed\n")
            with self.assertRaisesRegex(ValueError, "审查后源码变化"):
                merge.validate_baselines([path], self.root)

    def test_missing_source_hash_is_not_replaced_with_current_hash(self):
        path = self.root / "dossier.json"
        path.write_text(json.dumps({"baseline": {"head": "current"}, "features": []}))
        with patch.object(merge.subprocess, "check_output", return_value="current\n"):
            with self.assertRaisesRegex(ValueError, "source_hashes"):
                merge.validate_baselines([path], self.root)

    def test_cli_returns_two_and_writes_agent_queue_for_partial_work(self):
        data = report()
        data["features"][0]["gaps"] = ["尚未查奖励消费者"]
        path = self.root / "report.json"
        output = self.root / "queue.json"
        path.write_text(json.dumps(data))
        args = ["audit_completion.py", "--data", str(path), "--root", str(self.root),
                "--evidence-dir", str(self.evidence), "--output", str(output)]
        with patch("sys.argv", args), redirect_stdout(io.StringIO()):
            self.assertEqual(gate.main(), 2)
        self.assertFalse(json.loads(output.read_text())["ready_for_final"])

    def test_cli_does_not_accept_green_flags_without_report_schema(self):
        path = self.root / "report.json"
        output = self.root / "queue.json"
        path.write_text(json.dumps(report()))
        args = ["audit_completion.py", "--data", str(path), "--root", str(self.root),
                "--evidence-dir", str(self.evidence), "--output", str(output)]
        with patch("sys.argv", args), redirect_stdout(io.StringIO()):
            self.assertEqual(gate.main(), 2)
        self.assertIn("validation_error", json.loads(output.read_text()))


if __name__ == "__main__":
    unittest.main()
