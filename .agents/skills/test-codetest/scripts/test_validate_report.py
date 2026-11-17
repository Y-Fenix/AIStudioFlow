#!/usr/bin/env python3
"""Regression tests for report integrity, scope separation, and CLI failure behavior."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import validate_report as gate


class ReportGateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.baseline = "test-snapshot"
        for name, content in [("source.cs", "bool CanClaim(int now) => now < 200;\n"),
                              ("requirement.md", "资格截止时间为200，不含截止点。\n"),
                              ("run.json", '{"passed": 1, "failed": 0}\n')]:
            (self.root / name).write_text(content, encoding="utf-8")
        self.manifest = {"schema_version": 1, "cases": [{
            "key": "测试用例!2", "cells": ["到期", "资格", "等级8", "now=200", "不可领取", "活动"],
            "assertions": [{"id": "a", "text": "到期不可领取"}]}]}
        self.review = {"schema_version": 1, "scope": "code", "baseline": self.baseline,
                       "evidence": [self.evidence("code", "source", "source.cs"),
                                    self.evidence("rule", "requirement", "requirement.md")],
                       "cases": [{"key": "测试用例!2",
                                  "input_sha256": gate.fingerprint(self.manifest["cases"][0]["cells"]),
                                  "assertions": [{"id": "a", "text": "到期不可领取", "domain": "local",
                                                  "verdict": "pass", "method": "static", "input": "now=200",
                                                  "expected": "false", "actual": "false",
                                                  "reason": "200 < 200 为false", "evidence": ["rule", "code"]}]}]}
        requirement = self.evidence("req", "requirement", "requirement.md")
        log = self.evidence("read", "requirement", "run.json")
        snapshot = {k: requirement[k] for k in ("path", "sha256")}
        ledger = {"schema_version": 1, "selected_source_ids": ["req"], "sources": [{
            "id": "req", "title": "活动", "origin": "requirement.md", "version": snapshot["sha256"],
            "accessed_at": "2026-11-03T10:00:00+08:00", "snapshot": snapshot, "state": "read",
            "closure": {"complete": True, "note": "文件全量读取"}, "media": [],
            "inspection": {"method": "text", "artifact_sha256": snapshot["sha256"],
                           "evidence": {k: log[k] for k in ("path", "sha256")},
                           "locator": "全文读取回执", "findings": "到期不可领取"}}],
            "rules": [{"id": "rule", "source_id": "req", "locator": "正文", "text": "到期不可领取",
                       "media_keys": [], "state": "covered", "case_keys": ["测试用例!2"]}]}
        (self.root / "coverage.json").write_text(json.dumps(ledger), encoding="utf-8")
        binding = {"path": "coverage.json", "sha256": hashlib.sha256((self.root / "coverage.json").read_bytes()).hexdigest()}
        self.manifest["selected_source_ids"] = ["req"]
        self.manifest["source_coverage"] = binding
        self.review["source_coverage"] = binding.copy()

    def evidence(self, key, kind, path):
        record = {"id": key, "kind": kind, "path": path, "locator": "测试契约位置",
                  "sha256": hashlib.sha256((self.root / path).read_bytes()).hexdigest()}
        if kind != "requirement":
            record["baseline"] = self.baseline
        if kind == "source":
            record["line"] = 1
        return record

    @property
    def assertion(self):
        return self.review["cases"][0]["assertions"][0]

    def check(self):
        return gate.validate(self.manifest, self.review, self.root)

    def add_external(self):
        self.manifest["cases"][0]["assertions"].append({"id": "b", "text": "系统实际展示通知"})
        self.review["cases"][0]["assertions"].append({
            "id": "b", "text": "系统实际展示通知", "domain": "external", "verdict": "unresolved",
            "method": "none", "reason": "投递需要系统观察", "evidence": [],
            "external_variable": "iOS系统投递", "why_local_insufficient": "代码调度不证明系统实际展示",
            "blocker": {"kind": "external", "variable": "iOS系统投递",
                        "why_local_insufficient": "本地无法观察设备通知中心", "next_action": "观察目标设备",
                        "owner": "设备验收", "preparation": "保留原档，无需清档，通知权限允许",
                        "steps": "到期前退后台，等待目标触发点", "observation": "通知中心显示需求文案"}})

    def add_run(self):
        run = self.evidence("run", "run", "run.json")
        run.update(command=["python3", "tests.py"], cwd=str(self.root), runner="unittest",
                   run_id="actual-test-run", exit_code=0, discovered=1, passed=1, failed=0,
                   errors=0, skipped=0, results={"测试用例!2/a": "passed"})
        self.review["evidence"].append(run)
        self.assertion["method"] = "automated"
        self.assertion["evidence"].append("run")
        return run

    def test_static_pass_without_runtime(self):
        self.assertEqual(self.check()["counts"], {"测试通过（静态）": 1})

    def test_declared_cross_repo_binding_cannot_be_ignored(self):
        binding = {"profile": {"path": "missing.json", "sha256": "missing"}}
        self.manifest["cross_repo"] = binding
        self.review["cross_repo"] = copy.deepcopy(binding)
        with self.assertRaises(ValueError):
            self.check()

    def test_cross_repo_targets_require_binding(self):
        self.manifest['cases'][0]['assertions'][0]['cross_repo_targets'] = ['delivery.android']
        with self.assertRaises(ValueError):
            self.check()

    def bind_cross_repo(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        profile = {'schema_version': 1, 'project': 'fixture',
                   'repositories': {'client': {'anchors': ['source.cs']}},
                   'targets': [{'id': 'expiry', 'domain': 'installation', 'repositories': ['client']}]}
        snap = gate.cross_repo.snapshot(profile, {'client': str(self.root)}, {}, 'run')
        ledger = {'schema_version': 1, 'project': 'fixture', 'run_id': 'run', 'baseline': snap['digest'],
                  'assertions': [{'id': 'expiry', 'status': 'pass', 'input': 'now=200',
                                  'expected': 'false', 'actual': 'false', 'rule': 'requirement.md:1',
                                  'reason': '200 < 200 is false', 'evidence': [
                                      {'repo': 'client', 'path': 'source.cs', 'line': 1, 'quote': 'now < 200'}]}]}
        binding = {}
        for name, data in [('profile', profile), ('snapshot', snap), ('ledger', ledger)]:
            path = self.root / (name + '.json')
            path.write_text(json.dumps(data))
            binding[name] = {'path': path.name, 'sha256': gate.cross_repo.file_hash(path)}
        self.manifest['cross_repo'] = binding
        self.review['cross_repo'] = copy.deepcopy(binding)
        self.review['baseline'] = snap['digest']
        for e in self.review['evidence']:
            if 'baseline' in e:
                e['baseline'] = snap['digest']
        self.manifest['cases'][0]['assertions'][0]['cross_repo_targets'] = ['expiry']

    def test_bound_cross_repo_report_passes_static_only(self):
        self.bind_cross_repo()
        result = self.check()
        self.assertEqual(result['counts'], {'测试通过（静态）': 1})
        self.assertFalse(result['cross_repo']['release_verified'])

    def test_cross_repo_cannot_disagree_with_report_verdict(self):
        self.bind_cross_repo()
        path = self.root / 'ledger.json'
        ledger = json.loads(path.read_text())
        ledger['assertions'][0]['status'] = 'fail'
        path.write_text(json.dumps(ledger))
        for item in (self.manifest, self.review):
            item['cross_repo']['ledger']['sha256'] = gate.cross_repo.file_hash(path)
        with self.assertRaisesRegex(ValueError, 'cross_repo verdict mismatch'):
            self.check()

    def test_cross_repo_report_rechecks_source(self):
        self.bind_cross_repo()
        (self.root / 'source.cs').write_text('changed')
        for e in self.review['evidence']:
            if e['kind'] == 'source':
                e['sha256'] = gate.cross_repo.file_hash(self.root / 'source.cs')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            self.check()

    def test_missing_source_inventory_rejects_final_but_allows_explicit_partial(self):
        del self.manifest["source_coverage"]
        del self.review["source_coverage"]
        with self.assertRaisesRegex(gate.Invalid, "source_coverage required"):
            self.check()
        self.manifest["report_stage"] = self.review["report_stage"] = "partial"
        result = self.check()
        self.assertEqual(result["source_coverage"]["status"], "partial")
        self.assertEqual(result["counts"], {"测试通过（静态）": 1})
        self.assertTrue(result["source_coverage"]["gaps"])

    def test_changed_coverage_binding_rejected(self):
        self.review["source_coverage"]["sha256"] = "different"
        with self.assertRaisesRegex(gate.Invalid, "binding mismatch"):
            self.check()

    def test_partial_rules_block_final_without_changing_valid_case_result(self):
        path = self.root / "coverage.json"
        ledger = json.loads(path.read_text())
        ledger["rules"].append({"id": "missing-rule", "source_id": "req", "locator": "另一个明确条款",
                                "text": "重复点击只领奖一次", "media_keys": [], "state": "uncovered",
                                "reason": "尚未生成对应用例", "case_keys": []})
        path.write_text(json.dumps(ledger))
        binding = {"path": "coverage.json", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        self.manifest["source_coverage"] = self.review["source_coverage"] = binding
        with self.assertRaisesRegex(gate.Invalid, "incomplete"):
            self.check()
        self.manifest["report_stage"] = self.review["report_stage"] = "partial"
        self.assertEqual(self.check()["counts"], {"测试通过（静态）": 1})

    def test_code_result_keeps_external_residual(self):
        self.add_external()
        result = self.check()
        self.assertEqual(result["cases"][0]["result"], "测试通过（静态）")
        self.assertEqual(result["external_residual_assertions"], 1)
        self.review["scope"] = "full"
        self.assertEqual(self.check()["cases"][0]["result"], "需黑盒验证")

    def test_external_only_is_never_empty_pass(self):
        self.add_external()
        self.manifest["cases"][0]["assertions"].pop(0)
        self.review["cases"][0]["assertions"].pop(0)
        self.assertEqual(self.check()["cases"][0]["result"], "需黑盒验证")

    def test_missing_or_reordered_cases_rejected(self):
        original = copy.deepcopy(self.review)
        self.review["cases"] = []
        with self.assertRaises(gate.Invalid):
            self.check()
        self.review = original
        extra = copy.deepcopy(self.review["cases"][0])
        extra["key"] = "测试用例!3"
        self.review["cases"].append(extra)
        with self.assertRaises(gate.Invalid):
            self.check()

    def test_missing_assertion_rejected(self):
        self.add_external()
        self.review["cases"][0]["assertions"].pop()
        with self.assertRaises(gate.Invalid):
            self.check()

    def test_changed_original_rejected(self):
        self.manifest["cases"][0]["cells"][4] = "可以领取"
        with self.assertRaisesRegex(gate.Invalid, "six cells changed"):
            self.check()

    def test_stale_evidence_and_baseline_rejected(self):
        (self.root / "source.cs").write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(gate.Invalid, "sha256"):
            self.check()
        self.review["evidence"][0] = self.evidence("code", "source", "source.cs")
        self.review["evidence"][0]["baseline"] = "older"
        with self.assertRaisesRegex(gate.Invalid, "baseline"):
            self.check()

    def test_source_line_and_oracle_required(self):
        self.review["evidence"][0]["line"] = 20
        with self.assertRaisesRegex(gate.Invalid, "source line"):
            self.check()
        self.review["evidence"][0]["line"] = 1
        self.assertion["evidence"] = ["code"]
        with self.assertRaisesRegex(gate.Invalid, "expectation source"):
            self.check()

    def test_actual_mapped_run_and_zero_test_rejection(self):
        run = self.add_run()
        self.assertEqual(self.check()["cases"][0]["result"], "测试通过（自动化）")
        run["discovered"] = 0
        with self.assertRaises(gate.Invalid):
            self.check()

    def test_suite_failure_does_not_erase_target_pass(self):
        run = self.add_run()
        run.update(discovered=2, failed=1, exit_code=1)
        self.assertEqual(self.check()["cases"][0]["result"], "测试通过（自动化）")
        run["results"] = {"测试用例!2/a": "skipped"}
        with self.assertRaises(gate.Invalid):
            self.check()

    def test_unjustified_manual_transfer_rejected(self):
        self.assertion.update(verdict="unresolved", method="none", blocker={
            "kind": "external", "variable": "缺真实账号", "why_local_insufficient": "没有账号",
            "next_action": "人工造号", "owner": "测试"})
        with self.assertRaisesRegex(gate.Invalid, "cannot transfer"):
            self.check()

    def test_dynamic_deferral_requires_attempts(self):
        blocker = {"kind": "environment", "variable": "真实加载器依赖",
                   "why_local_insufficient": "需确认实际反序列化入口运行副作用", "next_action": "修复依赖",
                   "owner": "执行环境", "static_gap": "动态注册分派尚无法闭合",
                   "cannot_resolve_locally": "隔离运行依赖不在当前环境"}
        self.assertion.update(verdict="unresolved", method="none", blocker=blocker)
        with self.assertRaises(gate.Invalid):
            self.check()
        blocker["attempts"] = [{"strategy": strategy, "status": "unavailable", "result": "明确的缺失依赖"}
                               for strategy in ["static_trace", "fixture", "existing_runner"]]
        self.assertEqual(self.check()["cases"][0]["result"], "需自动化验证")

    def test_failure_is_valid_report_not_forced_green(self):
        self.assertion.update(verdict="fail", actual="true", reason="调用方反转返回值",
                              reachability="生产入口直接消费错误布尔值", steps="等于截止点进入领取入口")
        self.assertEqual(self.check()["counts"], {"测试不通过": 1})
        self.review["cases"][0]["result"] = "测试通过（静态）"
        with self.assertRaisesRegex(gate.Invalid, "disagrees"):
            self.check()

    def test_external_static_pass_and_missing_steps_rejected(self):
        self.add_external()
        external = self.review["cases"][0]["assertions"][1]
        del external["blocker"]["steps"]
        with self.assertRaisesRegex(gate.Invalid, "steps"):
            self.check()
        external.update(verdict="pass", method="static", input="time=200", expected="显示", actual="显示",
                        evidence=["code", "rule"])
        with self.assertRaisesRegex(gate.Invalid, "actual observation"):
            self.check()

    def test_external_failure_visible_even_when_code_passes(self):
        self.add_external()
        observation = self.evidence("screen", "observation", "run.json")
        self.review["evidence"].append(observation)
        external = self.review["cases"][0]["assertions"][1]
        external.update(verdict="fail", method="observed", input="目标时刻，权限允许",
                        expected="系统显示通知", actual="未显示", reason="本例的设备观察结果",
                        evidence=["rule", "screen"], reachability="已确认通知已调度且到期",
                        steps="退后台等待到期后查看通知中心")
        result = self.check()
        self.assertEqual(result["cases"][0]["result"], "测试通过（静态）")
        self.assertEqual(result["cases"][0]["external_failure_ids"], ["b"])
        self.review["scope"] = "full"
        self.assertEqual(self.check()["cases"][0]["result"], "测试不通过")

    def test_observed_only_pass_is_not_unnecessary_blackbox(self):
        self.add_external()
        self.review["evidence"].append(self.evidence("screen", "observation", "run.json"))
        self.manifest["cases"][0]["assertions"].pop(0)
        self.review["cases"][0]["assertions"].pop(0)
        external = self.review["cases"][0]["assertions"][0]
        external.update(verdict="pass", method="observed", input="已调度通知，权限允许",
                        expected="系统显示通知", actual="已显示", evidence=["rule", "screen"])
        self.assertEqual(self.check()["cases"][0]["result"], "测试通过（真实环境）")

    def test_obsolete_expectation_is_not_product_failure(self):
        self.assertion.update(verdict="obsolete", method="none", replacement="采用新版本截止规则")
        self.assertEqual(self.check()["cases"][0]["result"], "用例需更新")

    def test_mixed_static_and_automated_is_not_all_automated(self):
        self.add_run()
        self.manifest["cases"][0]["assertions"].append({"id": "b", "text": "调用方不进入发放"})
        extra = copy.deepcopy(self.assertion)
        extra.update(id="b", text="调用方不进入发放", method="static", evidence=["rule", "code"])
        self.review["cases"][0]["assertions"].append(extra)
        self.assertEqual(self.check()["cases"][0]["result"], "测试通过（静态）")

    def test_cli_nonzero_and_no_stale_output_overwrite(self):
        manifest = self.root / "input.json"
        review = self.root / "review.json"
        output = self.root / "validated.json"
        manifest.write_text(json.dumps(self.manifest), encoding="utf-8")
        review.write_text(json.dumps(self.review), encoding="utf-8")
        command = [sys.executable, str(Path(gate.__file__)), "--root", str(self.root),
                   "--input", str(manifest), "--review", str(review), "--output", str(output)]
        first = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        original = output.read_bytes()
        second = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(second.returncode, 1)
        self.assertEqual(output.read_bytes(), original)
        self.assertIn("REPORT_VALIDATION_FAILED", second.stderr)


if __name__ == "__main__":
    unittest.main()
