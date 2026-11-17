#!/usr/bin/env python3
"""Synthetic scope regressions; these tests make no game-quality claim."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import audit_scope as scope
import audit_completion
import finalize_report


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.evidence = self.root / "QA/results/synthetic"
        self.evidence.mkdir(parents=True)
        (self.root / "Code").mkdir()
        (self.root / "Code/Shop.cs").write_text("// synthetic shop\n")
        (self.root / "Code/Rank.cs").write_text("// synthetic rank\n")
        (self.root / "index.md").write_text("synthetic module index\n")
        self.path = self.root / "manifest.json"
        self.obj = {"scope_version": "synthetic-1", "watch_roots": ["Code"], "watch_files": ["index.md"],
                    "features": [{"id": name, "category": "系统", "group": "合成", "name": name,
                                  "sources": ["Code/" + name + ".cs"],
                                  "required_sources": ["Code/" + name + ".cs"],
                                  "check_targets": ["合成边界", "合成恢复"]} for name in ("Shop", "Rank")]}
        scope.save(self.path, self.obj)
        self.git = patch.object(scope.subprocess, "check_output", side_effect=self.git_output)
        self.git.start()
        self.addCleanup(self.git.stop)
        self.lock = scope.snapshot(self.root, "synthetic", self.path)
        scope.save(self.evidence / "scope-lock.json", self.lock)
        self.data = {"scope_control": {"mode": "full"}, "baseline": self.lock["baseline"], "features": scope.seed(self.lock)}

    def git_output(self, command, **kwargs):
        if command[-1] == "--show-toplevel":
            return str(self.root) + "\n"
        if command[-1] == "HEAD":
            return "synthetic-head\n"
        if command[-1] == "--show-current":
            return "synthetic-branch\n"
        return " synthetic-submodule submodule/path\n"

    def check(self, data=None, **kwargs):
        return scope.validate_scope(data or self.data, self.root, self.evidence, manifest_path=self.path, **kwargs)

    def test_fixed_inventory_is_not_a_pass_or_a_review(self):
        self.assertTrue(self.check()["ok"])
        self.assertEqual(self.lock["baseline"]["submodules"][0], " ")
        for feature in self.data["features"]:
            self.assertEqual(feature["static_audit"]["status"], "未完成")
            self.assertEqual(feature["source_paths"], [])

    def test_omitted_function_and_merged_large_group_are_rejected(self):
        self.data["features"] = [{**self.data["features"][0], "id": "SHOP-AND-RANK"}]
        result = self.check()
        self.assertFalse(result["ok"])
        self.assertEqual(result["missing_ids"], ["Rank", "Shop"])
        self.assertEqual(result["unexpected_ids"], ["SHOP-AND-RANK"])

    def test_duplicate_id_and_wrong_category_are_rejected(self):
        self.data["features"].append(deepcopy(self.data["features"][0]))
        self.data["features"][0]["display"]["category"] = "玩法"
        result = self.check()
        self.assertFalse(result["ok"])
        self.assertEqual(result["duplicate_ids"], ["Shop"])
        self.assertTrue(any("分类" in e for e in result["errors"]))

    def test_missing_lock_is_rejected(self):
        (self.evidence / "scope-lock.json").unlink()
        self.assertFalse(self.check()["ok"])

    def test_changed_source_same_head_cannot_reuse_lock(self):
        (self.root / "Code/Shop.cs").write_text("// changed\n")
        self.assertFalse(self.check()["ok"])

    def test_new_unassigned_entry_and_deleted_anchor_are_reported(self):
        (self.root / "Code/NewActivity.cs").write_text("// new\n")
        (self.root / "Code/Shop.cs").unlink()
        current = scope.snapshot(self.root, "synthetic", self.path)
        self.assertEqual(current["unassigned_sources"], ["Code/NewActivity.cs"])
        self.assertTrue(any("必备源码" in e for e in current["errors"]))
        self.assertFalse(self.check()["ok"])

    def test_changed_manifest_and_tampered_lock_are_rejected(self):
        self.lock["expected_count"] = 1
        scope.save(self.evidence / "scope-lock.json", self.lock)
        self.assertFalse(self.check()["ok"])
        self.obj["scope_version"] = "synthetic-2"
        scope.save(self.path, self.obj)
        self.assertFalse(self.check()["ok"])

    def test_new_run_old_lock_and_changed_index_are_rejected(self):
        self.data["baseline"] = {**self.data["baseline"], "run_id": "other"}
        self.assertFalse(self.check()["ok"])
        self.data["baseline"]["run_id"] = "synthetic"
        (self.root / "index.md").write_text("new module index\n")
        self.assertFalse(self.check()["ok"])

    def test_targeted_scope_requires_explicit_reason_and_never_passes_full_finalizer(self):
        self.data["scope_control"] = {"mode": "targeted", "reason": "用户指定合成模块", "feature_ids": ["Shop", "Rank"]}
        self.assertTrue(self.check()["ok"])
        self.assertFalse(self.check(require_full=True)["ok"])
        with self.assertRaisesRegex(ValueError, "固定范围"):
            finalize_report.verify_evidence(self.data, self.root, self.evidence)
        del self.data["scope_control"]["reason"]
        self.assertFalse(self.check()["ok"])

    def test_subcheck_requires_finished_scenario_and_source_evidence(self):
        owner = self.data["features"][0]
        owner["static_audit"]["cases"] = [{"scope_targets": ["合成边界", "合成恢复"], "verdict": "未检查", "trace": [{"path": "Code/Shop.cs"}]}]
        self.assertEqual(len(scope.target_gaps(owner, self.obj["features"][0])), 2)
        owner["static_audit"]["cases"][0]["verdict"] = "未见问题"
        self.assertEqual(scope.target_gaps(owner, self.obj["features"][0]), [])
        owner["static_audit"]["cases"][0]["trace"] = []
        self.assertEqual(len(scope.target_gaps(owner, self.obj["features"][0])), 2)

    def test_completion_returns_scope_gap_to_agent_even_if_report_omits_it(self):
        self.data["features"] = []
        def local_check(data, root, evidence):
            return scope.validate_scope(data, root, evidence, manifest_path=self.path)
        with patch.object(audit_completion, "validate_scope", side_effect=local_check), patch.object(audit_completion, "manifest", return_value=self.obj):
            queue = audit_completion.completion(self.data, self.root, self.evidence)
        self.assertFalse(queue["ready_for_final"])
        task = next(t for t in queue["tasks"] if t["id"] == "scope:inventory")
        self.assertEqual(task["agent"], "总控")
        self.assertTrue(any("Shop" in e for e in task["reasons"]))

    def test_invalid_manifest_cannot_hide_duplicate_ids_or_escape_root(self):
        self.obj["features"].append(deepcopy(self.obj["features"][0]))
        scope.save(self.path, self.obj)
        with self.assertRaisesRegex(ValueError, "重复"):
            scope.manifest(self.path)
        self.obj["features"].pop()
        self.obj["features"][0]["sources"] = ["../Other.cs"]
        scope.save(self.path, self.obj)
        with self.assertRaisesRegex(ValueError, "仓库内"):
            scope.manifest(self.path)


if __name__ == "__main__":
    unittest.main()
