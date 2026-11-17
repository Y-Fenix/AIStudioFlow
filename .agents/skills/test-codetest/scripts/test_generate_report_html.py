#!/usr/bin/env python3
"""Tests for the self-contained HTML report generator."""
import json
import hashlib
from pathlib import Path
import re
import shutil
import sys
import subprocess
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
import generate_report_html as report
import validate_report as gate


class HtmlReportTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node unavailable")
    def test_module_preview_matches_codex_backend_format(self):
        normalizer = re.search(r"^function codexModuleName\(value\).*$", report.HTML_TEMPLATE, re.M)
        self.assertIsNotNone(normalizer)
        script = normalizer.group(0) + '''
const values = ["✅三阶段竞速比赛", "三阶段竞速比赛", "【Codex-三阶段竞速比赛】", "【Codex-✅三阶段竞速比赛】"];
for (const value of values) {
 if (codexModuleName(value) !== "【Codex-三阶段竞速比赛】") throw Error(value);
}
if (codexModuleName("✅") !== "") throw Error("Empty module");
'''
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("需求模块:codexModuleName(cleanInline(c.module))", report.HTML_TEMPLATE)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.manifest = {
            "schema_version": 1,
            "cases": [{
                "key": "测试用例!2",
                "cells": ["活动 <边界>", "核对资格", "等级8", "时间设为200", "不可领取", "活动"],
                "assertions": [{"id": "a", "text": "到期不可领取"}],
            }],
        }
        self.review = {
            "schema_version": 1,
            "scope": "code",
            "baseline": "master@abc",
            "cases": [{
                "key": "测试用例!2",
                "assertions": [{
                    "id": "a", "domain": "local", "verdict": "pass", "method": "static",
                    "reason": "now < end", "evidence": ["rule", "source"],
                }],
            }],
        }
        self.validated = {
            "schema_version": 1,
            "scope": "code",
            "baseline": "master@abc",
            "cases": [{"key": "测试用例!2", "result": "测试通过（静态）"}],
        }
        for name, content in [("requirement.md", "到期不可领取"), ("source.cs", "return now < end;"),
                              ("read.json", '{"tool":"read","result":"全文已读"}')]:
            (self.root / name).write_text(content, encoding="utf-8")
        def ref(name):
            return {"path": name, "sha256": hashlib.sha256((self.root / name).read_bytes()).hexdigest()}
        source = {"id": "req", "title": "活动", "origin": "requirement.md", "version": ref("requirement.md")["sha256"],
                  "accessed_at": "2026-11-03T10:00:00+08:00", "snapshot": ref("requirement.md"), "state": "read",
                  "media": [], "closure": {"complete": True, "note": "读取全文"},
                  "inspection": {"method": "text", "artifact_sha256": ref("requirement.md")["sha256"],
                                 "evidence": ref("read.json"), "locator": "全文", "findings": "到期禁领"}}
        ledger = {"schema_version": 1, "selected_source_ids": ["req"], "sources": [source], "rules": [
            {"id": "r", "source_id": "req", "locator": "正文", "text": "到期不可领取", "media_keys": [],
             "state": "covered", "case_keys": ["测试用例!2"]}]}
        self.write_json("coverage.json", ledger)
        self.manifest["selected_source_ids"] = ["req"]
        self.manifest["source_coverage"] = self.review["source_coverage"] = ref("coverage.json")
        self.review["evidence"] = [
            {**ref("requirement.md"), "id": "rule", "kind": "requirement", "locator": "正文"},
            {**ref("source.cs"), "id": "source", "kind": "source", "locator": "逻辑", "line": 1, "baseline": "master@abc"}]
        self.review["cases"][0]["input_sha256"] = gate.fingerprint(self.manifest["cases"][0]["cells"])
        self.review["cases"][0]["assertions"][0].update(text="到期不可领取", input="now=end=200",
                                                        expected="false", actual="false")
        self.validated = gate.validate(self.manifest, self.review, self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def write_json(self, name, value):
        path = self.root / name
        if name == "validated.json":
            try:
                value = gate.validate(json.loads((self.root / "input.json").read_text()),
                                      json.loads((self.root / "review.json").read_text()), self.root)
            except ValueError:
                pass  # Intentionally invalid fixture is rejected by the generator.
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def test_build_cases_preserves_all_six_cells_and_result(self):
        cases = report.build_cases(self.manifest, self.review, self.validated)
        self.assertEqual(len(cases), 1)
        case = cases[0]
        self.assertEqual(case["content"], "活动 <边界>")
        self.assertEqual(case["expected"], "不可领取")
        self.assertEqual(case["result"], "测试通过（静态）")
        self.assertIn("now < end", case["basis"])

    def failing_case(self):
        assertion = self.review["cases"][0]["assertions"][0]
        assertion.update(verdict="fail", actual="到期后仍发放10金币", expected="不发放金币",
                         input="等级8；now=end=200；奖励未领取", reachability="打开活动奖励页",
                         steps="1. 设置时间为200\\n2、点击领取")
        passing = dict(assertion, id="passed", verdict="pass", actual="通过项不能混入缺陷",
                       expected="通过项预期不能混入缺陷")
        self.review["cases"][0]["assertions"].append(passing)
        return report.build_cases(self.manifest, self.review, self.validated)[0]

    def test_bug_draft_has_four_required_sections_from_failed_assertions_only(self):
        case = self.failing_case()
        draft = case["bug"]
        self.assertTrue(draft["ready"], draft["errors"])
        for label in ["前置条件", "操作步骤", "当前错误表现", "预期正确表现"]:
            self.assertIn(label, draft["description"])
        self.assertIn("等级8", draft["precondition"])
        self.assertIn("now=end=200", draft["precondition"])
        self.assertEqual(draft["steps"], "1、设置时间为200\n2、点击领取")
        self.assertEqual(draft["actual"], "到期后仍发放10金币")
        self.assertEqual(draft["expected"], "不发放金币")
        self.assertNotIn("通过项", draft["description"])
        self.assertNotIn("now < end", draft["actual"])
        self.assertIn("未真机复现", draft["description"])
        self.assertNotIn("必现", draft["description"])
        self.assertIn("source.cs:1", draft["evidence"])
        self.assertNotIn("[a]", draft["description"])
        self.assertEqual(case["expected"], "不可领取")

    def test_html_routes_failed_rows_to_clear_bug_copy_and_preview(self):
        self.failing_case()
        html = report.HTML_TEMPLATE
        self.assertIn("function displayBug(c)", html)
        self.assertIn("当前错误表现：${actual}", html)
        self.assertIn("function bugPreview(c)", html)
        self.assertIn("id=\"bugPreview\"", html)
        self.assertIn("待复核，不能提单", html)

    @unittest.skipUnless(shutil.which("node"), "Node unavailable")
    def test_bug_preview_renders_complete_and_blocked_records_without_writing(self):
        functions = report.HTML_TEMPLATE.split("function bugPreview(c)", 1)
        self.assertEqual(len(functions), 2, "Missing bug preview implementation")
        script = "function bugPreview(c)" + functions[1].split("function showMapping(", 1)[0]
        script = '''
const escapeHtml=v=>String(v??"").replaceAll("<","&lt;").replaceAll(">","&gt;");
const target={innerHTML:""};const $=()=>target;
const selectedCases=[{key:"失败项",bug:{ready:true,title:"<标题>",precondition:"等级8",steps:"1、点击领取",actual:"错误发奖",expected:"不应发奖"}},{key:"待复核项",bug:{ready:false,errors:["缺少当前错误表现"]}}];
''' + script + '''
renderBugPreview();
for(const value of ["&lt;标题&gt;","等级8","1、点击领取","错误发奖","不应发奖","缺少当前错误表现"]){if(!target.innerHTML.includes(value))throw Error(value);}
if(target.innerHTML.includes("<标题>"))throw Error("Unescaped preview");
'''
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_read_headers_is_read_only_and_does_not_run_submission_gate(self):
        html = report.HTML_TEMPLATE
        handler = html.split('$("readHeaders").addEventListener', 1)[1].split('$("importBug").addEventListener', 1)[0]
        self.assertNotIn("validateBugSelection();", handler)
        self.assertIn("const blocked=selectedCases.filter(c=>!c.bug?.ready).length", handler)
        self.assertIn("不能提单", handler)

    def test_bug_copy_is_explicit_and_incomplete_copy_blocks_submission(self):
        self.failing_case()
        a = self.review["cases"][0]["assertions"][0]
        a["bug"] = {"title": "到期点击领取仍发放金币", "precondition": "等级8，奖励未领，活动已经到期。",
                    "steps": ["将受控时钟设到活动结束时刻。", "点击领取。"],
                    "actual": "仍增加10金币。", "expected": "不发放奖励。"}
        case = report.build_cases(self.manifest, self.review, self.validated)[0]
        self.assertEqual(case["bug"]["title"], a["bug"]["title"])
        a["bug"]["actual"] = ""
        case = report.build_cases(self.manifest, self.review, self.validated)[0]
        self.assertFalse(case["bug"]["ready"])
        self.assertIn("当前错误表现", " ".join(case["bug"]["errors"]))

    def test_passing_case_cannot_be_submitted_as_bug(self):
        case = report.build_cases(self.manifest, self.review, self.validated)[0]
        self.assertFalse(case["bug"]["ready"])
        self.assertIn("没有失败断言", " ".join(case["bug"]["errors"]))

    def test_multiple_failures_keep_each_actual_paired_with_its_expected(self):
        self.failing_case()
        first = self.review["cases"][0]["assertions"][0]
        second = dict(first, id="b", actual="按钮仍可点击", expected="按钮不可点击")
        self.review["cases"][0]["assertions"].append(second)
        draft = report.build_cases(self.manifest, self.review, self.validated)[0]["bug"]
        self.assertTrue(draft["ready"])
        one, two = draft["description"].split("失败项2：", 1)
        self.assertIn("到期后仍发放10金币", one)
        self.assertIn("不发放金币", one)
        self.assertNotIn("按钮仍可点击", one)
        self.assertIn("按钮仍可点击", two)
        self.assertIn("按钮不可点击", two)
        self.assertNotIn("通过项", draft["description"])

    @unittest.skipUnless(shutil.which("node"), "Node unavailable")
    def test_live_ticket_mapping_uses_bug_copy_and_preserves_codex_fields(self):
        case = self.failing_case()
        script = report.HTML_TEMPLATE.split("function cleanText(value)", 1)[1]
        script = "function cleanText(value)" + script.split("function showMapping(", 1)[0]
        script = 'const text=v=>String(v??"");const REPORT={baseline:"master@abc"};\n' + script
        script += "\nconst c=" + json.dumps(case, ensure_ascii=False) + ";\n"
        script += '''
if(!standardValue("缺陷描述",c).startsWith("【静态检测】"))throw Error("prefix");
if(standardValue("实际表现",c)!=="到期后仍发放10金币")throw Error("actual");
if(standardValue("期望描述",c)!=="不发放金币")throw Error("expected");
if(!standardValue("前置条件",c).includes("等级8"))throw Error("precondition");
if(standardValue("版本号",c)!=="Codex")throw Error("version");
if(standardValue("功能模块",c)!=="【Codex-活动】")throw Error("module");
if(standardValue("复现率",c)!==""||standardValue("服务器",c)!==""||standardValue("平台",c)!=="")throw Error("invented metadata");
if(!standardValue("日志信息",c).includes("source.cs:1"))throw Error("evidence");
let selectedCases=[c];validateBugSelection();
selectedCases=[{key:"失败项",bug:{ready:false,errors:["缺少当前错误表现"]}}];
let blocked=false;
try{validateBugSelection();}catch(e){blocked=e.message.includes("缺少当前错误表现");}
if(!blocked)throw Error("incomplete ticket was not blocked");
'''
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_generate_is_self_contained_and_escapes_script_data(self):
        manifest = self.write_json("input.json", self.manifest)
        review = self.write_json("review.json", self.review)
        validated = self.write_json("validated.json", self.validated)
        output = self.root / "report.html"
        self.assertEqual(report.generate(manifest, review, validated, output, "<质量报告>", ""), 1)
        html = output.read_text(encoding="utf-8")
        self.assertIn("&lt;质量报告&gt;", html)
        self.assertIn("\\u003c边界>", html)
        self.assertIn("提单", html)
        self.assertIn("读取表头", html)
        self.assertIn("直接更新并提单", html)
        self.assertIn("【静态检测】", html)
        self.assertIn("飞书多维表格 URL", html)
        self.assertIn('id="newBug"', html)
        self.assertIn('id="selectVisible"', html)
        self.assertIn('id="selectAllVisible"', html)
        self.assertIn('class="case-check"', html)
        self.assertIn('const BUG_VERSION="Codex"', html)
        self.assertIn('版本号:BUG_VERSION', html)
        self.assertNotIn('String(REPORT.baseline).match(/v\\d+\\.\\d+\\.\\d+/)', html)
        self.assertIn("button.disabled=count===0", html)
        self.assertIn("批量导入 Bug 表格", html)
        self.assertIn("将批量导入 Bug 表格", html)
        self.assertIn("function toggleVisibleSelection()", html)
        self.assertIn("取消全选", html)
        self.assertIn("断言明细", html)
        self.assertIn("基线、校验统计与证据", html)
        self.assertIn("未发生任何写入", html)
        self.assertIn("const WRITE_AUTHORIZED = false", html)
        self.assertNotIn("confirm(", html)

    def test_authorized_report_enables_direct_submit(self):
        manifest = self.write_json("input.json", self.manifest)
        review = self.write_json("review.json", self.review)
        validated = self.write_json("validated.json", self.validated)
        output = self.root / "authorized.html"
        self.assertEqual(
            report.generate(manifest, review, validated, output, "报告", "", True),
            1,
        )
        source = output.read_text(encoding="utf-8")
        self.assertIn("const WRITE_AUTHORIZED = true", source)
        self.assertIn("本次已获提单授权", source)
        self.assertIn('credentials:BRIDGE?"omit":"include"', source)
        self.assertIn('credentials:"omit"', source)

    def test_feishu_bridge_mapping_and_error_detail_are_embedded(self):
        manifest = self.write_json("input.json", self.manifest)
        review = self.write_json("review.json", self.review)
        validated = self.write_json("validated.json", self.validated)
        output = self.root / "bridge.html"
        report.generate(manifest, review, validated, output, "报告", "http://127.0.0.1:8765", True)
        source = output.read_text(encoding="utf-8")
        self.assertIn('credentials:"omit"', source)
        self.assertIn("缺陷描述", source)
        self.assertIn("期望描述", source)
        self.assertIn("问题类型", source)
        self.assertIn("function responseError(response,prefix)", source)
        self.assertIn("桥接读取失败", source)
        self.assertIn("已提交 ${e.submitted}/${e.total} 条", source)
        self.assertIn("（${batches} 批）", source)

    def test_ticket_values_are_cleaned_for_human_readable_steps(self):
        manifest = self.write_json("input.json", {
            **self.manifest,
            "cases": [{
                "key": "测试用例!2",
                "cells": ["[expected] 活动\\n边界", "核对资格", "等级8", "1. 设置时间\\n2、点击入口", "[actual] 不可领取", "活动"],
                "assertions": [{"id": "a", "text": "到期不可领取"}],
            }],
        })
        review = self.write_json("review.json", {
            **self.review,
            "cases": [{
                "key": "测试用例!2",
                "input_sha256": gate.fingerprint(json.loads(manifest.read_text())["cases"][0]["cells"]),
                "assertions": [{
                    **self.review["cases"][0]["assertions"][0],
                    "id": "a", "domain": "local", "verdict": "pass", "method": "static",
                    "reason": "[expected] now < end\\n[oracle] boundary", "evidence": ["rule", "source"],
                }],
            }],
        })
        validated = self.write_json("validated.json", {
            **self.validated,
            "cases": [{"key": "测试用例!2", "result": "测试通过（静态）"}],
        })
        output = self.root / "report.html"
        report.generate(manifest, review, validated, output, "报告", "")
        source = output.read_text(encoding="utf-8")
        self.assertIn("function cleanText(value)", source)
        self.assertIn("function numberedSteps(value)", source)
        self.assertIn("function cleanOutcome(value)", source)
        self.assertIn("${index+1}、", source)
        self.assertIn(r"\[(?:expected|actual|oracle|result)\]", source)
        self.assertNotIn("标题:`[${result}] ${c.content}`", source)

    def test_new_bug_flow_enables_single_or_batch_selection(self):
        manifest = self.write_json("input.json", self.manifest)
        review = self.write_json("review.json", self.review)
        validated = self.write_json("validated.json", self.validated)
        output = self.root / "selection.html"
        report.generate(manifest, review, validated, output, "报告", "", True)
        source = output.read_text(encoding="utf-8")
        self.assertIn('id="newBug" type="button" disabled', source)
        self.assertIn('id="selectVisible" type="button" disabled', source)
        self.assertIn('id="selectAllVisible" class="case-check" type="checkbox"', source)
        self.assertIn('aria-label="选择用例 ${escapeHtml(c.key)}"', source)
        self.assertIn("function openNewBug(){if(!checkedKeys.size)return;openModal([...checkedKeys]);}", source)
        self.assertIn("button.disabled=count===0", source)
        self.assertIn("const rows=selectedCases.map(c=>headers.map(h=>standardValue(h,c)));", source)
        self.assertIn("caseKeys:selectedCases.map(c=>c.key)", source)
        self.assertIn("const visibleKeys=cases.filter(matches).map(c=>c.key);", source)
        self.assertIn("const allSelected=checkedKeys.size===visibleKeys.length&&visibleKeys.every(key=>checkedKeys.has(key));", source)
        self.assertIn("checkedKeys=allSelected?new Set():new Set(visibleKeys);", source)
        self.assertIn("checkedKeys.size===visibleKeys.length", source)
        self.assertIn("仅选择当前筛选结果", source)
        self.assertIn('$("selectAllVisible").addEventListener("change",toggleVisibleSelection)', source)
        self.assertIn('document.addEventListener("keydown"', source)

    def test_generate_refuses_overwrite(self):
        manifest = self.write_json("input.json", self.manifest)
        review = self.write_json("review.json", self.review)
        validated = self.write_json("validated.json", self.validated)
        output = self.root / "report.html"
        output.write_text("existing", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            report.generate(manifest, review, validated, output, "报告", "")

    def test_generated_javascript_parses_when_node_is_available(self):
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        manifest = self.write_json("input.json", self.manifest)
        review = self.write_json("review.json", self.review)
        validated = self.write_json("validated.json", self.validated)
        output = self.root / "report.html"
        report.generate(manifest, review, validated, output, "报告", "")
        source = output.read_text(encoding="utf-8")
        scripts = re.findall(r"<script>(.*?)</script>", source, re.S)
        self.assertEqual(len(scripts), 1)
        script = self.root / "report.js"
        script.write_text(scripts[0], encoding="utf-8")
        checked = subprocess.run(["node", "--check", str(script)], capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_mismatched_case_keys_are_rejected(self):
        manifest = self.write_json("input.json", self.manifest)
        review = self.write_json("review.json", {**self.review, "cases": []})
        validated = self.write_json("validated.json", self.validated)
        with self.assertRaises(ValueError):
            report.generate(manifest, review, validated, self.root / "report.html", "报告", "")

    def test_stale_validated_summary_cannot_generate_html(self):
        manifest = self.write_json("input.json", self.manifest)
        review = self.write_json("review.json", self.review)
        validated = self.write_json("validated.json", self.validated)
        data = json.loads(validated.read_text())
        data["cases"][0]["result"] = "测试不通过"
        validated.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "stale/changed"):
            report.generate(manifest, review, validated, self.root / "bad.html", "报告", "")

    def test_partial_report_displays_scope_gap_without_downgrading_code(self):
        self.manifest["report_stage"] = self.review["report_stage"] = "partial"
        del self.manifest["source_coverage"]
        del self.review["source_coverage"]
        manifest = self.write_json("input.json", self.manifest)
        review = self.write_json("review.json", self.review)
        validated = self.write_json("validated.json", self.validated)
        output = self.root / "partial.html"
        report.generate(manifest, review, validated, output, "报告", "")
        document = output.read_text()
        self.assertIn("阶段结果：", document)
        self.assertIn("旧表未建立来源/媒体清单", document)
        self.assertIn("测试通过（静态）", document)


if __name__ == "__main__":
    unittest.main()
