"""Quality-gate regressions for deterministic report accounting."""
from copy import deepcopy
import unittest

from quality_gate import build_quality_gate
import render_report
from test_static_audit import fixture


class QualityGateTests(unittest.TestCase):
    def complete_fixture(self):
        data = fixture()
        data["scope_control"] = {"mode": "targeted", "reason": "合成门禁测试，非项目全量", "feature_ids": ["fixture"]}
        data["features"][0]["static_audit"]["depth"] = {"branches": [{"id": "synthetic-branch"}]}
        return data

    def test_partial_review_is_explicit_even_when_findings_exist(self):
        data = fixture()
        data["agent_audit"] = {
            "inventory_count": 17,
            "deep_review_count": 1,
            "deep_review_complete": 1,
            "dossiers": ["dossiers/system.json"],
        }
        data["findings"] = [
            {"id": "BUG-2", "kind": "静态缺陷已证"},
            {"id": "BUG-2", "kind": "静态缺陷已证"},
        ]
        queue = {"ready_for_final": False, "tasks": [{"id": "feature:f-2"}]}
        gate = build_quality_gate(data, queue)
        self.assertEqual(gate["quality_status"], "部分完成")
        self.assertFalse(gate["audit_complete"])
        self.assertEqual(gate["confirmed_finding_count"], 1)
        self.assertEqual(gate["pending_task_count"], 1)

    def test_complete_review_has_stable_counts(self):
        data = self.complete_fixture()
        data["agent_audit"] = {
            "inventory_count": 1,
            "deep_review_count": 1,
            "deep_review_complete": 1,
            "dossiers": ["dossiers/system.json"],
        }
        queue = {"ready_for_final": True, "tasks": []}
        first = build_quality_gate(data, queue)
        second = build_quality_gate(deepcopy(data), queue)
        self.assertEqual(first, second)
        self.assertEqual(first["quality_status"], "通过")
        self.assertTrue(first["complete_review"])

    def test_stale_agent_counts_cannot_inflate_inventory_or_deep_review(self):
        data = fixture()
        data["agent_audit"] = {"inventory_count": 63, "deep_review_count": 63, "deep_review_complete": 63}
        gate = build_quality_gate(data, {"ready_for_final": True, "tasks": []})
        self.assertEqual(gate["inventory_count"], 1)
        self.assertEqual(gate["deep_review_complete"], 0)
        self.assertFalse(gate["audit_complete"])

    def test_green_queue_without_full_scope_lock_is_rejected(self):
        data = self.complete_fixture()
        del data["scope_control"]
        gate = build_quality_gate(data, {"ready_for_final": True, "tasks": []})
        self.assertFalse(gate["audit_complete"])
        self.assertFalse(gate["scope"]["ok"])

    def test_report_hash_ignores_only_embedded_snapshot(self):
        data = fixture()
        queue = {"ready_for_final": True, "tasks": []}
        first = build_quality_gate(data, queue)
        data["quality_gate"] = {"report_ready": True, "report_sha256": "later"}
        second = build_quality_gate(data, queue)
        self.assertEqual(first["report_data_sha256"], second["report_data_sha256"])
        data["presentation"]["conclusion"] = "changed"
        third = build_quality_gate(data, queue)
        self.assertNotEqual(first["report_data_sha256"], third["report_data_sha256"])

    def test_prepare_view_sorts_findings_and_features(self):
        data = fixture()
        feature = deepcopy(data["features"][0])
        feature["id"] = "a-feature"
        feature["display"] = dict(feature["display"], group="A组", name="A功能")
        data["features"][0]["id"] = "z-feature"
        data["features"][0]["display"] = dict(data["features"][0]["display"], group="Z组", name="Z功能")
        data["features"].append(feature)
        view = render_report.prepare_view(data)
        self.assertEqual([row["id"] for row in view["features"]], ["a-feature", "z-feature"])


if __name__ == "__main__":
    unittest.main()
