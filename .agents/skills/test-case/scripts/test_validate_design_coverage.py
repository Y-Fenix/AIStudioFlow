#!/usr/bin/env python3
"""Regression checks for missing coverage, unsupported exclusions and stale evidence."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import validate_design_coverage as gate


class CoverageGateTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {"schema_version": 1, "selected_source_ids": ["source"],
                         "cases": [{"key": "测试用例!2"}]}
        self.source = {"schema_version": 1, "selected_source_ids": ["source"],
                       "rules": [{"id": "rule", "state": "covered", "case_keys": ["测试用例!2"]}]}
        self.coverage = {"schema_version": 1, "selected_source_ids": ["source"], "checks": [], "items": []}
        for dim, topics in gate.TOPICS.items():
            item = {"id": dim, "dimension": dim, "basis": "需求第2节及已发布版本v1存档字段",
                    "status": "covered", "case_keys": ["测试用例!2"],
                    "scenario": {"input": "now=end；旧进度3/10；已报名", "sequence": "首启→迁移→回大厅→二启",
                                 "expected": "按独立需求到期关闭，旧进度保留且不重复奖励"}}
            if dim == "requirements":
                item["rule_ids"] = ["rule"]
            if dim == "coupling":
                item["path"] = ["活动到期", "结算队列", "奖励存档"]
            if dim == "upgrade":
                item.update(from_version="v1", old_state="进度3/10，未领奖")
            self.coverage["items"].append(item)
            self.coverage["checks"].extend({"dimension": dim, "topic": topic, "status": "applicable",
                                            "item_ids": [dim], "reason": "需求第2节及共享存档消费链"}
                                           for topic in sorted(topics))

    def check(self):
        return gate.validate(self.coverage, self.manifest, self.source)

    def test_one_case_can_cover_multiple_dimensions_without_inflation(self):
        result = self.check()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["case_count"], 1)
        self.assertTrue(all(d["total"] == 1 for d in result["dimensions"].values()))

    def test_missing_dimension_or_topic_is_rejected(self):
        self.coverage["checks"].pop()
        with self.assertRaisesRegex(ValueError, "missing topic"):
            self.check()

    def test_unknown_case_key_is_rejected(self):
        self.coverage["items"][0]["case_keys"] = ["测试用例!999"]
        with self.assertRaisesRegex(ValueError, "unknown case"):
            self.check()

    def test_source_rule_cannot_disappear(self):
        self.source["rules"].append({"id": "new-rule", "state": "uncovered", "case_keys": []})
        result = self.check()
        self.assertEqual(result["status"], "partial")
        self.assertIn("new-rule", str(result["gaps"]))

    def test_orphan_case_is_a_gap(self):
        self.manifest["cases"].append({"key": "测试用例!3"})
        self.assertEqual(self.check()["status"], "partial")

    def test_na_without_basis_is_rejected(self):
        self.coverage["checks"][0].update(status="not_applicable", item_ids=[], reason="")
        with self.assertRaisesRegex(ValueError, "basis/reason"):
            self.check()

    def test_na_with_basis_does_not_inflate_covered_count(self):
        self.coverage["checks"][0].update(status="not_applicable", item_ids=[], reason="本模块无配置文案，见来源第2节")
        result = self.check()
        self.assertEqual(result["dimensions"]["requirements"]["covered"], 1)
        self.assertEqual(result["dimensions"]["requirements"]["not_applicable_topics"], 1)

    def test_partial_and_ambiguous_are_not_covered(self):
        for status in ("partial", "missing", "ambiguous"):
            with self.subTest(status=status):
                self.coverage["items"][2].update(status=status, reason="缺旧版状态样本，影响截止期迁移预期")
                result = self.check()
                self.assertEqual(result["status"], "partial")
                self.assertEqual(result["dimensions"]["boundary"].get("covered", 0), 0)

    def test_covered_requires_concrete_scenario(self):
        for field in ("input", "sequence", "expected"):
            with self.subTest(field=field):
                snapshot = copy.deepcopy(self.coverage)
                self.coverage["items"][0]["scenario"][field] = ""
                with self.assertRaisesRegex(ValueError, "scenario"):
                    self.check()
                self.coverage = snapshot

    def test_upgrade_requires_old_version_and_state(self):
        self.coverage["items"][3].pop("old_state")
        with self.assertRaisesRegex(ValueError, "old_state"):
            self.check()

    def test_coupling_requires_distinct_nodes(self):
        self.coverage["items"][1]["path"] = ["活动", "活动"]
        with self.assertRaisesRegex(ValueError, "distinct"):
            self.check()

    def test_rule_mapping_must_match_actual_case(self):
        self.manifest["cases"].append({"key": "测试用例!3"})
        self.source["rules"][0]["case_keys"].append("测试用例!3")
        with self.assertRaisesRegex(ValueError, "source rule case mapping"):
            self.check()

    def test_selection_drift_is_rejected(self):
        self.coverage["selected_source_ids"] = ["other"]
        with self.assertRaisesRegex(ValueError, "mismatch"):
            self.check()

    def test_duplicate_topic_is_rejected(self):
        self.coverage["checks"].append(copy.deepcopy(self.coverage["checks"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate topic"):
            self.check()

    def test_unknown_applicability_is_a_gap(self):
        self.coverage["checks"][0].update(status="unknown", reason="未取得旧版本规则")
        self.assertEqual(self.check()["status"], "partial")

    def test_cli_validates_hashes_and_partial_cannot_bypass_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def save(name, value):
                path = root / name
                path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
                return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            snapshot = save("source.md", {"rule": "到期关闭，保留进度"})
            receipt = save("receipt.json", {"read": "全文"})
            self.source["sources"] = [{"id": "source", "title": "活动", "origin": "source.md",
                "version": snapshot["sha256"], "accessed_at": "2026-11-04T10:00:00+08:00",
                "snapshot": snapshot, "state": "read", "closure": {"complete": True, "note": "全文"},
                "media": [], "inspection": {"method": "text", "artifact_sha256": snapshot["sha256"],
                "evidence": receipt, "locator": "全文", "findings": "到期关闭，保留进度"}}]
            self.source["rules"][0].update(source_id="source", locator="第2节", text="到期关闭", media_keys=[])
            self.manifest["source_coverage"] = save("sources.json", self.source)
            save("input.json", self.manifest)
            save("coverage.json", self.coverage)
            command = [sys.executable, "-B", str(Path(gate.__file__)), "--coverage", str(root / "coverage.json"),
                       "--input", str(root / "input.json"), "--output", str(root / "validated.json")]
            run = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads((root / "validated.json").read_text())["status"], "complete")
            self.coverage["items"][2].update(status="missing", reason="尚缺到期边界资料")
            save("coverage.json", self.coverage)
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.manifest["report_stage"] = "partial"
            save("input.json", self.manifest)
            self.assertEqual(subprocess.run(command + ["--allow-partial"], capture_output=True).returncode, 0)
            self.coverage["checks"].pop()
            save("coverage.json", self.coverage)
            self.assertNotEqual(subprocess.run(command + ["--allow-partial"], capture_output=True).returncode, 0)
            save("source.md", {"rule": "内容已变"})
            failed = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("sha256", failed.stderr)


if __name__ == "__main__":
    unittest.main()
