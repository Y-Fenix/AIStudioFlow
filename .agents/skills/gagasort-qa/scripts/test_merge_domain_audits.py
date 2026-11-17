#!/usr/bin/env python3
"""深审 dossier 门禁测试：防止薄弱盘点被伪装成七维深审。"""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import merge_domain_audits as merge


def dossier():
    feature = {"id": "feature-1", "name": "测试功能", "related_findings": []}
    branches = []
    checks = []
    coverage = []
    for i, dim in enumerate(merge.DIMENSIONS, 1):
        bid = f"branch-{i}"
        cid = f"case-{i}"
        branches.append({
            "id": bid, "dimension": dim, "condition": f"触发{dim}分支",
            "consumer": "最终状态消费者", "evidence": [{"path": "Fixture.cs", "line": 1}],
        })
        checks.append({
            "case_id": cid, "dimension": dim, "topic": f"检查{dim}",
            "scenario": f"按真实顺序检查{dim}", "finding": "当前代码满足约束",
            "branch_ids": [bid], "finding_ids": [],
            "evidence": [{"path": "Fixture.cs", "line": 1}],
        })
        coverage.append({"dimension": dim, "status": "已闭合", "branch_ids": [bid], "case_ids": [cid]})
    return feature, {"branches": branches, "coverage": coverage, "checks": checks}


class DeepDossierTests(unittest.TestCase):
    def test_finding_verdict_preserves_evidence_layer(self):
        for kind, expected in (("静态缺陷已证", "发现静态缺陷"),
                               ("方法问题已证", "发现方法级问题"),
                               ("产品问题已证", "发现产品问题")):
            self.assertEqual(merge.finding_verdict(["issue"], {"issue": kind}), expected)

    def test_visual_risk_status_is_preserved(self):
        with TemporaryDirectory() as temp_dir:
            evidence = Path(temp_dir)
            data = {"level_audit": {"visual": {"status": "有风险待确认"}}}
            merge.normalize_level_audit(data, evidence)
            self.assertEqual(data["level_audit"]["visual"]["status"], "有风险待确认")

    def test_old_shallow_dossier_is_rejected(self):
        feature, detail = dossier()
        del detail["branches"]
        with self.assertRaises(ValueError):
            merge.validate_dossier_feature(detail, feature)

    def test_branch_requires_consumer(self):
        feature, detail = dossier()
        del detail["branches"][0]["consumer"]
        with self.assertRaises(ValueError):
            merge.validate_dossier_feature(detail, feature)

    def test_orphan_branch_is_rejected(self):
        feature, detail = dossier()
        detail["branches"].append({
            "id": "orphan", "dimension": merge.DIMENSIONS[0], "condition": "孤立",
            "consumer": "消费者", "evidence": [{"path": "Fixture.cs", "line": 1}],
        })
        with self.assertRaises(ValueError):
            merge.validate_dossier_feature(detail, feature)

    def test_closed_dimension_requires_case(self):
        feature, detail = dossier()
        detail["coverage"][0]["case_ids"] = []
        with self.assertRaises(ValueError):
            merge.validate_dossier_feature(detail, feature)

    def test_unchecked_dimension_requires_specific_gap(self):
        feature, detail = dossier()
        detail["coverage"][0].update(status="未检查")
        with self.assertRaises(ValueError):
            merge.validate_dossier_feature(detail, feature)

    def test_case_must_explicitly_declare_findings(self):
        feature, detail = dossier()
        del detail["checks"][0]["finding_ids"]
        with self.assertRaises(ValueError):
            merge.validate_dossier_feature(detail, feature)

    def test_feature_finding_must_attach_to_a_specific_case(self):
        feature, detail = dossier()
        feature["related_findings"] = ["finding-1"]
        with self.assertRaises(ValueError):
            merge.validate_dossier_feature(detail, feature)

    def test_complete_deep_v2_dossier_is_accepted(self):
        feature, detail = dossier()
        normalized, _, _ = merge.validate_dossier_feature(detail, feature)
        self.assertEqual(len(normalized["branches"]), len(merge.DIMENSIONS))
        self.assertEqual(len(normalized["checks"]), len(merge.DIMENSIONS))

    def test_dossier_findings_and_feature_links_are_collected(self):
        feature, detail = dossier()
        finding = {"id": "finding-1", "kind": "方法问题已证"}
        feature["related_findings"] = [finding["id"]]
        detail["checks"][0]["finding_ids"] = [finding["id"]]
        dossier_feature = {**feature, **detail}
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "dossier.json"
            path.write_text(json.dumps({"features": [dossier_feature], "findings": [finding]}))
            base_feature = {"id": feature["id"], "related_findings": []}
            dossiers, findings = merge.collect_dossiers([path], [base_feature])

        self.assertEqual(findings, [finding])
        self.assertEqual(base_feature["related_findings"], [finding["id"]])
        normalized, _, _ = merge.validate_dossier_feature(dossiers[feature["id"]][1], base_feature)
        self.assertEqual(normalized["checks"][0]["finding_ids"], [finding["id"]])

    def test_dossier_finding_id_conflict_is_rejected(self):
        feature, _ = dossier()
        with TemporaryDirectory() as temp_dir:
            paths = []
            for index, finding in enumerate([
                {"id": "finding-1", "kind": "方法问题已证"},
                {"id": "finding-1", "kind": "静态缺陷已证"},
            ]):
                path = Path(temp_dir) / f"{index}.json"
                path.write_text(json.dumps({"features": [feature] if index == 0 else [], "findings": [finding]}))
                paths.append(path)
            with self.assertRaisesRegex(ValueError, "同名记录字段冲突"):
                merge.collect_dossiers(paths, [feature])

    def test_same_finding_can_merge_complementary_fields(self):
        feature, _ = dossier()
        with TemporaryDirectory() as temp_dir:
            paths = []
            for index, finding in enumerate([
                {"id": "finding-1", "kind": "方法问题已证", "title": "奖励门禁遗漏"},
                {"id": "finding-1", "kind": "方法问题已证", "reproduction": ["步骤一"]},
            ]):
                path = Path(temp_dir) / f"{index}.json"
                path.write_text(json.dumps({"features": [feature] if index == 0 else [], "findings": [finding]}))
                paths.append(path)
            _, findings = merge.collect_dossiers(paths, [feature])

        self.assertEqual(findings[0]["title"], "奖励门禁遗漏")
        self.assertEqual(findings[0]["reproduction"], ["步骤一"])

    def test_dossier_link_without_finding_record_is_rejected(self):
        feature, _ = dossier()
        feature["related_findings"] = ["missing-finding"]
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "dossier.json"
            path.write_text(json.dumps({"features": [feature], "findings": []}))
            with self.assertRaisesRegex(ValueError, "缺少finding记录"):
                merge.collect_dossiers([path], [feature])


if __name__ == "__main__":
    unittest.main(verbosity=2)
