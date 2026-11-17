#!/usr/bin/env python3
"""Delivery regressions use synthetic data only; they do not test the game."""
from contextlib import redirect_stdout
from copy import deepcopy
import csv
import io
import json
from pathlib import Path
import sys
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import finalize_report as delivery
import merge_solver_extension as extension
import record_run
from level_3d_checks import relation, smoke
from supplement_level_visuals import merge_clear
from test_static_audit import fixture
import render_report


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.out = self.root / "QA/results/synthetic"
        self.out.mkdir(parents=True)
        self.source = self.root / "Production.cs"
        self.source.write_text("synthetic input\n")
        self.baseline = dict(root=str(self.root), head="fixture-head", branch="fixture-branch", run_id="synthetic")
        delivery.save(self.out / "baseline.json", self.baseline)

    def run_local(self, run_id="RUN-ONE", command=None, outputs=None):
        command = command or [sys.executable, "-c", "print('synthetic check only')"]
        args = ["record_run.py", "--root", str(self.root), "--evidence-dir", str(self.out), "--run-id", run_id,
                "--source", "Production.cs"]
        for name in outputs or []:
            args += ["--output", name]
        args += ["--", *command]
        def git_output(command, **kwargs):
            return "fixture-branch\n" if command[-1] == "--show-current" else "fixture-head\n"
        stream = io.StringIO()
        with patch("sys.argv", args), patch.object(record_run.subprocess, "check_output", side_effect=git_output), redirect_stdout(stream):
            code = record_run.main()
        run = json.loads(stream.getvalue())
        return code, run

    def data(self, run):
        return dict(baseline=self.baseline, suites=[run], additional_runs=[])

    def test_declared_cross_repo_evidence_cannot_be_ignored(self):
        data = dict(baseline=self.baseline, cross_repo={})
        with self.assertRaises(ValueError):
            delivery.verify_cross_repo(data, self.root, self.out)

    def test_legacy_delivery_without_cross_repo_binding_still_supported(self):
        self.assertIsNone(delivery.verify_cross_repo({'baseline': self.baseline}, self.root, self.out))

    def test_cross_repo_pending_keeps_completion_open(self):
        queue = {'ready_for_final': True, 'tasks': [], 'summary': {}}
        cross = {'counts': {'unreviewed': 2, 'blocked': 1}, 'baseline': 'digest'}
        delivery.apply_cross_repo_completion(queue, cross)
        self.assertFalse(queue['ready_for_final'])
        self.assertEqual(queue['summary']['cross_repo_pending_assertions'], 3)

    def cross_repo_data(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        profile = {'schema_version': 1, 'project': 'gagasort',
                   'repositories': {'client': {'anchors': ['Production.cs']}},
                   'targets': [{'id': 'a', 'domain': 'iap', 'repositories': ['client']}]}
        snap = delivery.cross_repo.snapshot(profile, {'client': str(self.root)}, {}, 'synthetic')
        ledger = {'schema_version': 1, 'project': 'gagasort', 'run_id': 'synthetic',
                  'baseline': snap['digest'], 'assertions': [{'id': 'a', 'status': 'unreviewed', 'reason': 'not reviewed'}]}
        refs = {'baseline': snap['digest']}
        for key, value in [('profile', profile), ('snapshot', snap), ('ledger', ledger)]:
            path = self.out / (key + '-cross.json')
            delivery.save(path, value)
            refs[key] = {'path': str(path), 'sha256': delivery.digest(path)}
        return {'baseline': dict(self.baseline, head=snap['repositories']['client']['head']), 'cross_repo': refs}

    def test_cross_repo_delivery_binds_current_project_run_and_source(self):
        data = self.cross_repo_data()
        result = delivery.verify_cross_repo(data, self.root, self.out)
        self.assertEqual(result['counts'], {'unreviewed': 1})
        self.assertFalse(result['release_verified'])
        self.source.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            delivery.verify_cross_repo(data, self.root, self.out)

    def test_cross_repo_delivery_rejects_other_run(self):
        data = self.cross_repo_data()
        data['baseline']['run_id'] = 'another-run'
        with self.assertRaisesRegex(ValueError, '本项目本轮'):
            delivery.verify_cross_repo(data, self.root, self.out)

    def test_record_actual_command_and_verify_its_original_bytes(self):
        code, run = self.run_local()
        self.assertEqual(code, 0)
        delivery.verify_execution_receipts(self.data(run), self.root, self.out)
        self.assertEqual((self.out / run["evidence"]).read_text(), "synthetic check only\n")

    def test_old_run_receipt_cannot_be_relabelled_as_a_new_audit(self):
        _, run = self.run_local()
        data = self.data(run)
        data["baseline"] = dict(self.baseline, run_id="another-run")
        with self.assertRaisesRegex(ValueError, "不属于本轮"):
            delivery.verify_execution_receipts(data, self.root, self.out)

    def test_modified_log_and_production_input_are_rejected(self):
        _, run = self.run_local()
        log = self.out / run["evidence"]
        original = log.read_bytes()
        log.write_text("copied old success\n")
        with self.assertRaisesRegex(ValueError, "日志内容变化"):
            delivery.verify_execution_receipts(self.data(run), self.root, self.out)
        log.write_bytes(original)
        self.source.write_text("changed after check\n")
        with self.assertRaisesRegex(ValueError, "执行输入已变化"):
            delivery.verify_execution_receipts(self.data(run), self.root, self.out)

    def test_input_change_during_command_is_not_complete(self):
        code, run = self.run_local(command=[sys.executable, "-c", "from pathlib import Path; Path('Production.cs').write_text('changed')"])
        self.assertEqual(code, 2)
        with self.assertRaisesRegex(ValueError, "输入期间变化"):
            delivery.verify_execution_receipts(self.data(run), self.root, self.out)

    def test_missing_expected_artifact_is_not_success(self):
        code, run = self.run_local(outputs=["missing-output.json"])
        self.assertEqual(code, 2)
        with self.assertRaisesRegex(ValueError, "产物缺失"):
            delivery.verify_execution_receipts(self.data(run), self.root, self.out)

    def test_preexisting_output_cannot_get_a_new_execution_signature(self):
        (self.out / "old-output.json").write_text("old success")
        with self.assertRaisesRegex(ValueError, "不能给旧产物补签"):
            self.run_local(outputs=["old-output.json"])

    def test_failed_command_is_an_actual_run_not_a_business_pass(self):
        code, run = self.run_local(command=[sys.executable, "-c", "print('expected failure'); raise SystemExit(7)"])
        self.assertEqual(code, 7)
        self.assertEqual(run["exit_code"], 7)
        delivery.verify_execution_receipts(self.data(run), self.root, self.out)
        run["status"] = "局部验证通过"
        with self.assertRaisesRegex(ValueError, "非零退出码不能标通过"):
            delivery.verify_execution_receipts(self.data(run), self.root, self.out)

    def test_original_run_id_cannot_be_overwritten(self):
        self.run_local()
        with self.assertRaises(FileExistsError):
            self.run_local()

    def test_missing_receipt_is_rejected_even_when_a_log_exists(self):
        _, run = self.run_local()
        del run["execution_receipt"]
        with self.assertRaisesRegex(ValueError, "缺本轮执行回执"):
            delivery.verify_execution_receipts(self.data(run), self.root, self.out)

    def test_timeout_receipt_must_remain_blocked(self):
        _, run = self.run_local()
        path = self.out / run["execution_receipt"]
        receipt = delivery.read(path)
        receipt.update(state="unknown", exit_code=124)
        delivery.save(path, receipt)
        run.update(exit_code=124, status="局部测试通过")
        with self.assertRaisesRegex(ValueError, "执行未结束"):
            delivery.verify_execution_receipts(self.data(run), self.root, self.out)
        run["status"] = "执行受阻·超时"
        delivery.verify_execution_receipts(self.data(run), self.root, self.out)

    def test_corrupt_data_invalidates_previous_success_first(self):
        delivery.save(self.out / "delivery-check.json", dict(report_ready=True, audit_complete=True))
        (self.out / "report-data.json").write_text("{broken")
        args = ["finalize_report.py", "--root", str(self.root), "--evidence-dir", str(self.out)]
        with patch("sys.argv", args), redirect_stdout(io.StringIO()):
            self.assertEqual(delivery.main(), 2)
        result = delivery.read(self.out / "delivery-check.json")
        self.assertFalse(result["report_ready"])
        self.assertEqual(result["status"], "交付校验失败")

    def test_changed_template_is_rejected_before_render(self):
        template = delivery.SKILL / "assets/report-template.html"
        changed = self.out / "changed.html"
        changed.write_bytes(template.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "模板与已确认版本不一致"):
            render_report.render({}, self.out, self.out / "report.html", changed)

    def test_exports_preserve_zero_and_false_and_derive_counts(self):
        data = fixture()
        data["baseline"].update(head="synthetic", branch="synthetic")
        data["configuration_cases"] = [dict(name="zero", input=0, status=False)]
        data["level_audit"]["visual"] = dict(summary="synthetic visual check only")
        delivery.export_results(data, self.out)
        with (self.out / "configuration.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.reader(stream))
        self.assertEqual(rows[1][2:4], ["0", "False"])
        self.assertIn("已确认问题：0", (self.out / "audit.md").read_text())

    def solver_fixture(self):
        levels = self.out / "levels"
        levels.mkdir()
        rows = [dict(level_id=str(i), status="Unknown", validation=dict(valid=True)) for i in (1, 2, 3)]
        rows[0].update(status="Solvable", replay=dict(has_completed=True, independent_runtime=True))
        rows[2].update(status="Invalid", validation=dict(valid=False))
        delivery.save(levels / "level-inventory.json", dict(levels=[dict(level_id=str(i)) for i in (1, 2, 3)]))
        delivery.save(levels / "solver-kernel.json", dict(levels=rows, budget=dict(ms=1)))
        extra = deepcopy(rows)
        extra[0].update(status="Unknown", replay={})
        extra[1].update(status="Solvable", replay=dict(has_completed=True, independent_runtime=True))
        extended = levels / "extended.json"
        delivery.save(extended, dict(levels=extra, budget=dict(ms=2)))
        result = [dict(level_id=str(i), evidence=["levels/details/" + str(i) + ".json"]) for i in (1, 2, 3)]
        (levels / "details").mkdir()
        for i in (1, 2, 3):
            delivery.save(levels / "details" / (str(i) + ".json"), dict(visual=dict(supplement_3d="preserved")))
        delivery.save(levels / "solvability-results.json", dict(results=result))
        delivery.save(levels / "report-fragment.json", dict(table=[dict(level_id=str(i)) for i in (1, 2, 3)],
                      visual=dict(summary="unchanged-3D"), solvability={}, summary_rows=[dict(id="solver")]))
        (levels / "solver-input.json").write_text("synthetic levels input")
        manifest = levels / "manifest.json"
        self.save_solver_manifest(levels, extended, manifest)
        return levels, extended, manifest

    def save_solver_manifest(self, levels, extended, manifest):
        import hashlib
        digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        delivery.save(manifest, dict(head=self.baseline["head"], head_after=self.baseline["head"],
                      repo=str(self.root), exit_code=0, sources_changed=[], sources=[],
                      input_sha256=digest(levels / "solver-input.json"), output_sha256=digest(extended)))

    def test_extension_keeps_proved_solution_and_3d_supplement(self):
        levels, extended, manifest = self.solver_fixture()
        with patch.object(extension.subprocess, "check_output", return_value=self.baseline["head"]):
            result = extension.merge(levels, extended, "RUN-EXTEND", manifest)
        self.assertEqual((result["success"], result["unknown"], result["problems"]), (2, 0, 1))
        self.assertEqual(delivery.read(levels / "report-fragment.json")["visual"]["summary"], "unchanged-3D")
        self.assertEqual(delivery.read(levels / "details/1.json")["visual"]["supplement_3d"], "preserved")

    def test_extension_rejects_duplicate_ids_without_claiming_success(self):
        levels, extended, manifest = self.solver_fixture()
        data = delivery.read(extended)
        data["levels"][2] = data["levels"][1]
        delivery.save(extended, data)
        self.save_solver_manifest(levels, extended, manifest)
        with patch.object(extension.subprocess, "check_output", return_value=self.baseline["head"]), self.assertRaisesRegex(ValueError, "清单完全一致"):
            extension.merge(levels, extended, "RUN-EXTEND", manifest)

    def test_second_extension_cannot_weaken_first_extension_solution(self):
        levels, extended, manifest = self.solver_fixture()
        with patch.object(extension.subprocess, "check_output", return_value=self.baseline["head"]):
            extension.merge(levels, extended, "RUN-EXTEND", manifest)
            second = levels / "second-extension.json"
            data = delivery.read(extended)
            data["levels"][1].update(status="Unknown", replay={})
            delivery.save(second, data)
            self.save_solver_manifest(levels, second, manifest)
            result = extension.merge(levels, second, "RUN-EXTEND-SECOND", manifest)
        self.assertEqual(result["success"], 2)
        self.assertEqual(len(delivery.read(levels / "details/2.json")["solver_attempts"]), 3)

    def test_same_level_ids_with_old_inputs_cannot_be_merged(self):
        levels, extended, manifest = self.solver_fixture()
        (levels / "solver-input.json").write_text("changed same IDs")
        with self.assertRaisesRegex(ValueError, "不是本轮相同输入"):
            extension.merge(levels, extended, "RUN-EXTEND", manifest)

    def test_3d_smoke_includes_height_separation_and_crossing(self):
        self.assertIn("height-separated", smoke())
        a = [[0, 0, 0], [4, 0, 0], [0, 4, 0]]
        b = [[.5, .5, 2], [2, .5, 2], [.5, 2, 2]]
        self.assertEqual(relation(a, b)["kind"], "height_separated")

    def test_3d_clear_cannot_hide_other_gap_or_existing_risk(self):
        levels = self.out / "levels"
        levels.mkdir()
        rows = [dict(level_id=str(i), verdict="未定", wall_risk=i == 3, water_risk=False,
                     errors=["非平面动态路径"] + (["missing source"] if i == 2 else []),
                     evidence=["levels/details/" + str(i) + ".json"]) for i in (1, 2, 3)]
        (levels / "details").mkdir()
        for i in (1, 2, 3):
            delivery.save(levels / "details" / (str(i) + ".json"), dict(visual={}))
        delivery.save(levels / "visual-summary.json", dict(results=rows, total=3))
        delivery.save(levels / "report-fragment.json", dict(table=[dict(level_id=str(i)) for i in (1, 2, 3)], risks=[],
                      visual=dict(summary="synthetic", evidence=[], wall_risk_count=0, water_risk_count=0), summary_rows=[]))
        proof = dict(levels=[dict(level_id=str(i), sources=[dict(clear=True)]) for i in (1, 2, 3)])
        self.assertEqual(merge_clear(levels, proof), ["1"])
        result = delivery.read(levels / "visual-summary.json")
        self.assertEqual([r["verdict"] for r in result["results"]], ["未见问题", "未定", "未定"])


if __name__ == "__main__":
    unittest.main()
