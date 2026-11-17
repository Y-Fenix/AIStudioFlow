#!/usr/bin/env python3
"""Generate a self-contained, filterable HTML report from the report contract files.

The skill obtains explicit user consent before enabling external bug-sheet writes.
The report can read JSON/HTML table headers directly when CORS permits, or use a
local bridge that implements the documented /schema and /import endpoints. The
browser still requires a deliberate click on the submit button; no write happens
while loading the page or reading a URL.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import re
import sys

from validate_report import validate


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def esc_script(value) -> str:
    """Serialize JSON safely inside a script tag."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def evidence_text(assertions, key: str, field: str) -> str:
    values = []
    for assertion in assertions:
        value = assertion.get(field)
        if value:
            values.append(f"[{assertion.get('id', '')}] {value}")
        if field == "reason" and assertion.get("evidence"):
            values.append(f"证据: {', '.join(assertion['evidence'])}")
    return "\n".join(values) or "-"


def clean_bug_text(value):
    if isinstance(value, list):
        value = "\n".join(str(item) for item in value)
    return re.sub(r"\[(?:expected|actual|oracle|result)\]\s*", "",
                  str(value or "").replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n"),
                  flags=re.I).strip()


def bug_steps(value):
    lines = [re.sub(r"^\d+[、.)]\s*", "", line.strip())
             for line in clean_bug_text(value).splitlines() if line.strip()]
    return "\n".join(f"{index}、{line}" for index, line in enumerate(lines, 1))


def build_bug_draft(source, assertions, evidence):
    """Build ticket copy from failed assertions without altering review verdicts."""
    failed = [a for a in assertions if a.get("verdict") == "fail"]
    draft = dict(ready=False, errors=[], title="", precondition="", steps="", actual="",
                 expected="", description="", evidence="", verification="")
    if not failed:
        draft["errors"] = ["没有失败断言，不能作为缺陷提单"]
        return draft
    refs = {item["id"]: item for item in evidence}
    parts, locations = [], []
    labels = {"precondition": "前置条件", "steps": "操作步骤", "actual": "当前错误表现",
              "expected": "预期正确表现", "title": "问题标题"}
    for index, a in enumerate(failed, 1):
        copy = a.get("bug", {})
        if not isinstance(copy, dict):
            draft["errors"].append(f"失败项{index}：缺陷文案必须是对象")
            copy = {}
        defaults = dict(title=a.get("actual", ""), precondition=a.get("input", ""),
                        steps=a.get("steps", ""), actual=a.get("actual", ""), expected=a.get("expected", ""))
        part = {key: (bug_steps(copy.get(key, value)) if key == "steps"
                      else clean_bug_text(copy.get(key, value))) for key, value in defaults.items()}
        for key, label in labels.items():
            if not part[key]:
                draft["errors"].append(f"失败项{index}：缺少{label}")
        if a.get("method") == "static":
            part["verification"] = "代码推导，未真机复现；以下为受控输入对应的代码行为。"
        elif a.get("method") == "observed":
            part["verification"] = "实际观察；适用范围以所附观察记录为准。"
        else:
            part["verification"] = "本地自动化验证，未真机复现；结论限于本地测试输入和替身环境。"
        parts.append(part)
        for ref in a.get("evidence", []):
            item = refs.get(ref, {})
            if item.get("path"):
                location = item["path"] + (f":{item['line']}" if item.get("line") else "")
                locator = clean_bug_text(item.get("locator", ""))
                locations.append(location + (f" · {locator}" if locator else ""))
    for key in ("title", "precondition", "steps", "actual", "expected", "verification"):
        draft[key] = parts[0][key] if len(parts) == 1 else "\n\n".join(
            f"失败项{index}：{part[key]}" for index, part in enumerate(parts, 1))
    blocks = []
    for index, part in enumerate(parts, 1):
        title = part["title"] if len(parts) == 1 else f"失败项{index}：{part['title']}"
        blocks.append("\n\n".join([title, "验证方式：" + part["verification"],
            "前置条件：\n" + part["precondition"], "操作步骤：\n" + part["steps"],
            "当前错误表现：\n" + part["actual"], "预期正确表现：\n" + part["expected"]]))
    draft["description"] = "\n\n".join(blocks)
    draft["evidence"] = "\n".join(dict.fromkeys(locations))
    if not draft["evidence"]:
        draft["errors"].append("缺少可定位的代码或需求依据")
    draft["ready"] = not draft["errors"]
    return draft


def build_cases(manifest, review, validated):
    inputs = {item["key"]: item for item in manifest.get("cases", [])}
    reviews = {item["key"]: item for item in review.get("cases", [])}
    results = {item["key"]: item for item in validated.get("cases", [])}
    if set(inputs) != set(reviews) or set(inputs) != set(results):
        raise ValueError("input/review/validated case keys do not match")

    cases = []
    for key, source in inputs.items():
        review_case = reviews[key]
        result_case = results[key]
        cells = source.get("cells", [])
        assertions = review_case.get("assertions", [])
        cases.append({
            "key": key,
            "content": cells[0] if len(cells) > 0 else "",
            "purpose": cells[1] if len(cells) > 1 else "",
            "precondition": cells[2] if len(cells) > 2 else "",
            "steps": cells[3] if len(cells) > 3 else "",
            "expected": cells[4] if len(cells) > 4 else "",
            "module": cells[5] if len(cells) > 5 else "",
            "result": result_case.get("result", "未生成结果"),
            "basis": evidence_text(assertions, key, "reason"),
            "automation": evidence_text(assertions, key, "method"),
            "residual": "\n".join(
                f"[{a.get('id', '')}] {a.get('blocker', {}).get('variable', '') or a.get('external_variable', '') or a.get('reason', '')}"
                for a in assertions
                if a.get("verdict") == "unresolved" or a.get("domain") == "external"
            ) or "-",
            "assertions": assertions,
            "bug": build_bug_draft(source, assertions, review.get("evidence", [])),
            "externalResidualIds": result_case.get("external_residual_ids", []),
            "externalFailureIds": result_case.get("external_failure_ids", []),
        })
    return cases


HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f4f7fb;--ink:#172033;--muted:#61708a;--line:#dfe6f0;--primary:#2764e7;--primary-dark:#1747b8;--danger:#c7354d;--warn:#b36b00;--ok:#16835b;--card:#fff;--shadow:0 12px 30px rgba(25,47,88,.10)}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.top{background:linear-gradient(115deg,#162950,#244fa8);color:#fff;padding:28px 32px 24px}.top h1{margin:0 0 8px;font-size:24px;letter-spacing:.2px}.top p{margin:0;color:#dce7ff}.wrap{max-width:1800px;margin:0 auto;padding:22px 24px 48px}.summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:18px}.metric{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;box-shadow:var(--shadow)}.metric strong{display:block;font-size:24px}.metric span{color:var(--muted);font-size:12px}.toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:14px;box-shadow:var(--shadow)}input,select,button{font:inherit}input,select{border:1px solid #cbd6e5;border-radius:8px;background:#fff;color:var(--ink);padding:9px 11px;min-height:38px}input.search{min-width:280px;flex:1}button{border:0;border-radius:8px;padding:9px 13px;cursor:pointer;font-weight:600;min-height:38px}button.primary{background:var(--primary);color:#fff}button.primary:hover{background:var(--primary-dark)}button.secondary{background:#eaf0fc;color:#214ba8}button.ghost{background:#eef2f7;color:#34425a}button.danger{background:#ffe8ed;color:#a8263d}.hint{color:var(--muted);font-size:12px;margin-left:auto}.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow);margin-bottom:14px;padding:14px}.panel summary{cursor:pointer;font-weight:700;color:#33496f}.evidence-table{margin-top:12px;overflow:auto}.evidence-table table{min-width:760px}.table-shell{background:var(--card);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow);overflow:auto}.count{padding:12px 14px;color:var(--muted);border-bottom:1px solid var(--line)}table{border-collapse:separate;border-spacing:0;width:100%;min-width:1900px}th,td{padding:11px 12px;border-bottom:1px solid var(--line);vertical-align:top;text-align:left;white-space:pre-wrap}th{position:sticky;top:0;background:#f8faff;color:#3b4c68;font-size:12px;z-index:2}tbody tr:hover{background:#f8fbff}td.key{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#52627b;font-size:12px;white-space:nowrap}td.content{min-width:180px;max-width:280px}td.long{min-width:230px;max-width:370px}.assertions{min-width:240px;max-width:360px}.assertions summary{cursor:pointer;color:#2a58bd;font-weight:600}.assertions pre{white-space:pre-wrap;word-break:break-word;font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;color:#45536a}.chip{display:inline-flex;align-items:center;border-radius:999px;padding:3px 9px;font-size:12px;font-weight:700;white-space:nowrap}.pass{background:#e2f7ee;color:var(--ok)}.fail{background:#ffe4e9;color:var(--danger)}.pending{background:#fff0d8;color:var(--warn)}.other{background:#e9edf4;color:#52627b}.actions{white-space:nowrap}.modal-backdrop{display:none;position:fixed;inset:0;background:rgba(17,30,56,.50);z-index:20;padding:24px;overflow:auto}.modal-backdrop.open{display:flex;align-items:flex-start;justify-content:center}.modal{width:min(1280px,calc(100vw - 32px));max-height:calc(100vh - 48px);display:flex;flex-direction:column;overflow:hidden;background:#fff;border-radius:14px;box-shadow:0 20px 60px rgba(0,0,0,.28);margin:0 auto;padding:22px}.modal h2{margin:0 0 4px}.modal .sub{color:var(--muted);font-size:12px;margin-bottom:15px}.modal-row{display:flex;gap:8px;margin:10px 0}.modal-row input{flex:1;min-width:0}.status{margin:10px 0;padding:10px 12px;border-radius:8px;background:#f2f5f9;white-space:pre-wrap}.status.error{background:#ffe8ed;color:#a8263d}.status.success{background:#e2f7ee;color:#116846}.mapping{flex:1;min-height:130px;max-height:min(52vh,540px);overflow:auto;border:1px solid var(--line);border-radius:8px;margin:12px 0}.mapping table{width:max-content;min-width:100%;table-layout:auto}.mapping th,.mapping td{padding:7px 9px}.mapping th{font-size:11px;line-height:1.3;white-space:nowrap;word-break:keep-all;min-width:96px}.mapping td{font-size:11px;line-height:1.45;min-width:120px;max-width:360px;white-space:pre-wrap;overflow-wrap:anywhere}.mapping th:first-child,.mapping td:first-child{position:sticky;left:0;z-index:3;background:#f8faff;min-width:110px;max-width:150px}.mapping th:first-child{z-index:4}.footer-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:16px;flex-shrink:0}.empty{text-align:center;color:var(--muted);padding:34px}.check{display:flex;align-items:center;gap:6px;color:var(--muted);font-size:13px}@media(max-width:720px){.top{padding:22px 18px}.wrap{padding:16px 12px}.search{min-width:160px!important}.hint{width:100%;margin-left:0}.modal-backdrop{padding:10px}.modal{width:100%;max-height:calc(100vh - 20px);padding:16px}.mapping{max-height:55vh}.mapping th{font-size:10px;min-width:88px}.mapping td{font-size:10px;min-width:108px}}
/* Design-system overrides: dense QA dashboard with a restrained navy/amber hierarchy. */
:root{--bg:#eef2f7;--ink:#142238;--muted:#607089;--line:#d5deea;--primary:#1e40af;--primary-dark:#17358f;--accent:#d97706;--danger:#b4233c;--warn:#9a5a00;--ok:#087443;--card:#fff;--navy:#142b52;--shadow:0 10px 26px rgba(20,43,82,.08)}
*{box-sizing:border-box}body{background:var(--bg)}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.top{background:var(--navy);border-bottom:4px solid var(--accent)}.top-meta{display:flex;gap:12px;align-items:center;margin-bottom:8px;color:#9fb5d5;font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase}.top-meta::before{content:"QA";display:inline-grid;place-items:center;width:24px;height:24px;border:1px solid #7189b0;border-radius:6px;color:#fff;letter-spacing:0}
.metric{position:relative;overflow:hidden;border-radius:10px}.metric::before{content:"";position:absolute;inset:0 auto 0 0;width:4px;background:var(--primary)}.metric:nth-child(2)::before{background:var(--ok)}.metric:nth-child(3)::before{background:var(--danger)}.metric:nth-child(4)::before{background:var(--accent)}
.toolbar{border-radius:10px;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px 16px;align-items:center}.toolbar-group{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.toolbar-group.filters{min-width:0}.selection-status{color:var(--muted);font-size:12px;white-space:nowrap}button.bulk-submit{background:var(--accent);color:#fff;min-width:126px;box-shadow:0 4px 10px rgba(217,119,6,.22)}button.bulk-submit:hover:not(:disabled){background:#b65f05}button:disabled{cursor:not-allowed;opacity:.48;box-shadow:none}
tbody tr.selected-row{background:#edf5ff;box-shadow:inset 3px 0 0 var(--primary)}.select-col{width:48px;text-align:center}.case-check{width:18px;height:18px;accent-color:var(--primary);cursor:pointer}
.select-visible{min-width:126px}.select-visible.is-selected{background:#fff3dc;color:#915800;border-color:#e7b66c}
.check{white-space:nowrap}
.modal{border:1px solid #cfd9e6;border-radius:12px;padding:24px}.field-label{display:block;font-size:12px;font-weight:700;color:#344866;margin:12px 0 6px}.modal-row{margin:0}.modal-row input{flex:1}.modal-backdrop{background:rgba(17,30,56,.58)}
.bug-preview-list{display:grid;gap:10px;max-height:34vh;overflow:auto;margin:12px 0}.bug-preview{border:1px solid #c9d9f3;border-left:4px solid var(--primary);border-radius:8px;background:#f8fbff;padding:12px 14px}.bug-preview.blocked{border-left-color:var(--warn);background:#fffaf1}.bug-preview-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.bug-preview-head strong{font-size:13px;line-height:1.45}.copy-badge{display:inline-block;white-space:nowrap;padding:2px 7px;border-radius:999px;background:#e6eefc;color:#2456c6;font-size:11px}.blocked .copy-badge{background:#fff0d8;color:#996000}.bug-preview dl{display:grid;grid-template-columns:88px 1fr;gap:6px 10px;margin:10px 0 0;font-size:12px}.bug-preview dt{font-weight:700;color:#52627b}.bug-preview dd{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}.preview-warning{margin:10px 0 0;color:#996000;font-size:12px}.tech-detail{margin-top:7px;font-size:11px;color:#52627b}.tech-detail summary{cursor:pointer}
button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:3px solid rgba(217,119,6,.45);outline-offset:2px}@media(prefers-reduced-motion:reduce){button{transition:none}}@media(max-width:1100px){.toolbar{grid-template-columns:1fr}.toolbar-group.actions{justify-content:flex-start}.hint{grid-column:auto;margin-left:0}}@media(max-width:720px){.toolbar-group.filters{min-width:100%}.selection-status{width:100%}.modal-row{flex-direction:column}.modal-row button{width:100%}}
</style>
<style>
/* QA console refresh: compact, readable, and source-status first. */
:root{--bg:#f6f8fb;--ink:#172033;--muted:#64748b;--line:#d9e2ee;--primary:#2456c6;--primary-dark:#183f9d;--accent:#c86b08;--danger:#b4233c;--warn:#996000;--ok:#087443;--navy:#162d52;--card:#fff;--shadow:0 4px 16px rgba(20,43,82,.07)}
body{background:var(--bg);color:var(--ink);font-size:14px}
.top{padding:20px 32px 18px;background:var(--navy);border-bottom:3px solid var(--accent)}
.top h1{font-size:22px;margin-bottom:5px}.top p{font-size:12px;color:#c7d5eb}
.wrap{max-width:1880px;padding:18px 24px 42px}
.panel,.metric,.toolbar,.table-shell{border-radius:8px;box-shadow:var(--shadow)}
#sourceCoverage{padding:16px 18px;background:#fbfcfe;border-left:4px solid var(--primary)}
.coverage-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:12px}.coverage-head strong{font-size:14px}.coverage-head .coverage-note{margin:3px 0 0;color:var(--muted);font-size:12px}
.coverage-grid{display:grid;grid-template-columns:repeat(4,minmax(140px,1fr));gap:8px}.coverage-stat{padding:10px 12px;border:1px solid var(--line);border-radius:7px;background:#fff}.coverage-stat b{display:block;font-size:20px;line-height:1.1}.coverage-stat span{display:block;margin-top:3px;color:var(--muted);font-size:11px}.coverage-stat.good{border-color:#b9e3d0;background:#f3fbf7}.coverage-stat.warn{border-color:#f0d4a7;background:#fffaf0}.coverage-stat.neutral{border-color:#cbd9f5;background:#f5f8ff}
.coverage-gaps{margin-top:12px;border-top:1px solid var(--line);padding-top:8px}.coverage-gaps summary{font-size:12px;color:#465a76}.coverage-gaps ul{margin:8px 0 0;padding-left:20px;max-height:180px;overflow:auto;color:var(--muted);font-size:12px}
.summary{gap:9px;margin:14px 0}.metric{padding:12px 14px}.metric strong{font-size:22px}.metric span{font-size:11px}
.toolbar{padding:12px;gap:9px;background:#fff}.toolbar-group.filters{gap:7px}.toolbar-group.actions{gap:7px}input,select,button{min-height:36px}input,select{padding:8px 10px;border-radius:7px}input.search{min-width:260px}button{padding:8px 12px;border-radius:7px;transition:background .18s ease,transform .18s ease}button:hover:not(:disabled){transform:translateY(-1px)}button.bulk-submit{min-width:132px}
.selection-status{font-weight:600;color:#435675}.hint{font-size:11px}
.table-shell{border-radius:8px}.count{padding:10px 13px;font-size:12px}.table-shell table{min-width:1840px}th{background:#f2f5fa;padding:10px 11px;color:#334967;font-size:11px}td{padding:10px 11px;font-size:12px}tbody tr{transition:background .15s ease}tbody tr.selected-row{background:#eef5ff;box-shadow:inset 3px 0 0 var(--primary)}
.chip{padding:3px 8px;font-size:11px}.actions .primary{font-size:12px}.case-check{width:17px;height:17px}
.modal-backdrop{background:rgba(10,23,45,.62)}.modal{border-radius:10px;padding:22px;border-color:#cbd7e7}.modal h2{font-size:19px}.modal .sub{max-width:100%;overflow-wrap:anywhere}.mapping{border-radius:7px}.status{border-radius:7px;font-size:12px}
/* Bound the actual scroll container so sticky headings stay visible on long reports. */
.table-shell{max-height:80vh;max-height:80dvh;overflow:auto;scrollbar-gutter:stable}
.table-shell thead th{position:sticky;top:0;z-index:5;box-shadow:0 1px 0 var(--line)}
.table-shell:focus-visible{outline:2px solid var(--primary);outline-offset:2px}
@media(max-width:900px){.coverage-grid{grid-template-columns:repeat(2,minmax(140px,1fr))}.coverage-head{display:block}.coverage-head .coverage-note{margin-top:5px}}
@media(max-width:720px){.top{padding:18px}.wrap{padding:14px 10px 32px}.coverage-grid{grid-template-columns:repeat(2,1fr)}.toolbar{padding:10px}.toolbar-group.filters,.toolbar-group.actions{width:100%}input.search{min-width:0;width:100%}.hint{width:100%;margin-left:0}}
</style>
</head>
<body>
<header class="top"><div class="top-meta">Quality Assurance Report</div><h1>__TITLE__</h1><p>代码初步质量报告 · 基线：__BASELINE__ · 口径：__SCOPE__</p></header>
<main class="wrap">
__COVERAGE__
<section id="summary" class="summary"></section>
<details class="panel"><summary>基线、校验统计与证据（点击展开）</summary><div id="evidenceBox" class="evidence-table"></div></details>
<section class="toolbar">
  <div class="toolbar-group filters"><input id="search" class="search" placeholder="搜索用例、步骤、预期、模块或检测依据" aria-label="搜索测试用例"><select id="resultFilter" aria-label="按测试结果筛选"><option value="">全部测试结果</option></select><select id="moduleFilter" aria-label="按需求模块筛选"><option value="">全部需求模块</option></select><label class="check"><input id="residualOnly" type="checkbox"> 仅看未决/外部残留</label></div>
  <div class="toolbar-group actions"><button class="secondary" id="exportVisible" type="button">导出当前筛选 JSON</button><button class="secondary select-visible" id="selectVisible" type="button" disabled>全选当前筛选</button><button class="bulk-submit" id="newBug" type="button" disabled title="请先选择用例">新建提单</button><span id="selectionStatus" class="selection-status" role="status" aria-live="polite">未选择用例</span></div>
  <span id="writeHint" class="hint"></span>
</section>
<section class="table-shell" tabindex="0" aria-label="测试用例表格，可上下左右滚动"><div id="count" class="count"></div><table><thead><tr>
<th class="select-col"><input id="selectAllVisible" class="case-check" type="checkbox" aria-label="全选当前筛选结果"><span class="sr-only">全选当前筛选结果</span></th><th>位置</th><th>测试内容</th><th>测试目的</th><th>前置条件</th><th>操作步骤</th><th>期望结果</th><th>需求模块</th><th>测试结果</th><th>检测依据</th><th>自动化执行情况</th><th>真实环境残留</th><th>断言明细</th><th>操作</th>
</tr></thead><tbody id="rows"></tbody></table></section>
</main>
<div id="modalBackdrop" class="modal-backdrop"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="modalTitle">
  <h2 id="modalTitle">新建 Bug 单</h2><div id="modalSub" class="sub"></div>
  <label class="field-label" for="sheetUrl">飞书多维表格 URL</label><div class="modal-row"><input id="sheetUrl" type="url" autocomplete="url" placeholder="粘贴飞书多维表格 URL（或已授权桥接接口 URL）"><button class="secondary" id="readHeaders" type="button">读取表头</button></div>
  <div id="modalStatus" class="status"></div>
  <div id="bugPreview" class="bug-preview-list"></div>
  <div id="mappingBox" class="mapping" hidden></div>
  <div class="footer-actions"><button class="ghost" id="closeModal">关闭</button><button class="primary" id="importBug" disabled>直接更新并提单</button></div>
</section></div>
<script>
const REPORT = __DATA__;
const BRIDGE = __BRIDGE__;
const WRITE_AUTHORIZED = __WRITE_AUTHORIZED__;
const cases = REPORT.cases || [];
let visible = cases.slice();
let selected = null;
let selectedCases = [];
let checkedKeys = new Set();
let lastFocused = null;
let remote = null;
const $ = id => document.getElementById(id);
const text = value => value == null ? "" : String(value);
function escapeHtml(value){const div=document.createElement("div");div.textContent=text(value);return div.innerHTML;}
function resultClass(result){if(result.includes("不通过"))return "fail";if(result.includes("通过"))return "pass";if(result.includes("需")||result.includes("证据")||result.includes("待"))return "pending";return "other";}
function buildOptions(){
  const results=[...new Set(cases.map(c=>c.result))].sort(); const modules=[...new Set(cases.map(c=>c.module).filter(Boolean))].sort();
  for(const [id,items] of [["resultFilter",results],["moduleFilter",modules]]) for(const item of items){const o=document.createElement("option");o.value=item;o.textContent=item;$(id).appendChild(o);}
}
function renderSummary(){
  const counts=Object.keys(REPORT.counts||{}).length?{总数:cases.length,...REPORT.counts}:{总数:cases.length}; for(const c of cases)if(!counts[c.result])counts[c.result]=1;
  $("summary").innerHTML=Object.entries(counts).map(([k,v])=>`<div class="metric"><strong>${escapeHtml(v)}</strong><span>${escapeHtml(k)}</span></div>`).join("");
}
function renderEvidence(){const evidence=REPORT.evidence||[];const rows=evidence.map(e=>`<tr><td>${escapeHtml(e.id)}</td><td>${escapeHtml(e.kind)}</td><td>${escapeHtml(e.path)}</td><td>${escapeHtml(e.locator)}</td></tr>`).join("");$("evidenceBox").innerHTML=`<p><b>基线：</b>${escapeHtml(REPORT.baseline)}　<b>口径：</b>${escapeHtml(REPORT.scope)}　<b>证据数：</b>${escapeHtml(evidence.length)}</p>${evidence.length?`<table><thead><tr><th>ID</th><th>类型</th><th>文件</th><th>定位</th></tr></thead><tbody>${rows}</tbody></table>`:"<p class=hint>没有附加证据条目。</p>"}`;}
function displayBug(c){return c.bug||null;}
function displayModule(c){return codexModuleName(cleanInline(c.module))||cleanInline(c.module);}
function matches(c){const q=$("search").value.trim().toLowerCase();const result=$("resultFilter").value;const module=$("moduleFilter").value;const residual=$("residualOnly").checked;const b=displayBug(c);const hay=[c.key,c.content,c.purpose,c.precondition,c.steps,c.expected,c.module,c.result,c.basis,c.automation,c.residual,b?.title,b?.precondition,b?.steps,b?.actual,b?.expected,b?.description].join("\n").toLowerCase();return(!q||hay.includes(q))&&(!result||c.result===result)&&(!module||c.module===module)&&(!residual||c.residual!=="-");}
function updateSelectionSummary(){const count=checkedKeys.size;const button=$("newBug");button.disabled=count===0;button.title=count===0?"请先选择用例":`使用已选 ${count} 条用例新建 Bug 单`;$("selectionStatus").textContent=count===0?"未选择用例":`已选择 ${count} 条`;document.querySelectorAll(".case-check[data-key]").forEach(box=>{const row=box.closest("tr");row.classList.toggle("selected-row",box.checked);});const visibleKeys=cases.filter(matches).map(c=>c.key);const selectedVisible=visibleKeys.filter(key=>checkedKeys.has(key)).length;const allVisible=visibleKeys.length>0&&selectedVisible===visibleKeys.length&&checkedKeys.size===visibleKeys.length;const selectAll=$("selectAllVisible");selectAll.checked=allVisible;selectAll.indeterminate=selectedVisible>0&&!allVisible;selectAll.disabled=visibleKeys.length===0;const selectButton=$("selectVisible");selectButton.disabled=visibleKeys.length===0;selectButton.textContent=allVisible?"取消全选":"全选当前筛选";selectButton.classList.toggle("is-selected",allVisible);selectButton.title=allVisible?"取消选择当前筛选结果":"仅选择当前筛选结果";}
function toggleVisibleSelection(){const visibleKeys=cases.filter(matches).map(c=>c.key);if(!visibleKeys.length)return;const allSelected=checkedKeys.size===visibleKeys.length&&visibleKeys.every(key=>checkedKeys.has(key));checkedKeys=allSelected?new Set():new Set(visibleKeys);render();}
function render(){visible=cases.filter(matches);$("count").textContent=`当前显示 ${visible.length} / ${cases.length} 条`;$("rows").innerHTML=visible.length?visible.map(c=>{const b=displayBug(c);const title=b?.title||c.content;const pre=b?.precondition||c.precondition;const steps=b?.steps||c.steps;const expected=b?.expected||c.expected;const actual=b?.actual||"";const basis=actual?`当前错误表现：${actual}`:c.basis;return `<tr class="${checkedKeys.has(c.key)?"selected-row":""}">
<td class="select-col"><input class="case-check" type="checkbox" data-key="${escapeHtml(c.key)}" ${checkedKeys.has(c.key)?"checked":""} aria-label="选择用例 ${escapeHtml(c.key)}"></td><td class="key">${escapeHtml(c.key)}</td><td class="content">${escapeHtml(title)}${b?`<div class="copy-badge">缺陷文案</div>`:""}</td><td class="content">${escapeHtml(c.purpose)}</td><td class="long">${escapeHtml(pre)}</td><td class="long">${escapeHtml(steps)}</td><td class="long">${escapeHtml(expected)}</td><td>${escapeHtml(displayModule(c))}</td><td><span class="chip ${resultClass(c.result)}">${escapeHtml(c.result)}</span></td><td class="long">${escapeHtml(basis)}${b&&c.basis?`<details class="tech-detail"><summary>查看技术依据</summary><pre>${escapeHtml(c.basis)}</pre></details>`:""}</td><td>${escapeHtml(c.automation)}</td><td class="long">${escapeHtml(c.residual)}</td><td class="assertions"><details><summary>${escapeHtml(c.assertions.length)} 条断言</summary><pre>${escapeHtml(JSON.stringify(c.assertions,null,2))}</pre></details></td><td class="actions"><button class="primary fileBug" type="button" data-key="${escapeHtml(c.key)}">提单</button></td></tr>`}).join(""):"<tr><td colspan=14 class=empty>没有符合筛选条件的用例</td></tr>";document.querySelectorAll(".fileBug").forEach(b=>b.addEventListener("click",()=>openModal(b.dataset.key)));document.querySelectorAll(".case-check[data-key]").forEach(box=>box.addEventListener("change",()=>{if(box.checked)checkedKeys.add(box.dataset.key);else checkedKeys.delete(box.dataset.key);updateSelectionSummary();}));updateSelectionSummary();}
function openNewBug(){if(!checkedKeys.size)return;openModal([...checkedKeys]);}
function setStatus(message,kind=""){const el=$("modalStatus");el.textContent=message;el.className=`status ${kind}`;}
function openModal(keys){const list=Array.isArray(keys)?keys:[keys];selectedCases=list.map(key=>cases.find(c=>c.key===key)).filter(Boolean);selected=selectedCases[0]||null;if(!selected)return;lastFocused=document.activeElement;remote=null;$("modalSub").textContent=selectedCases.length===1?`${selected.key} · ${selected.content}`:`已选择 ${selectedCases.length} 条用例，将批量导入 Bug 表格`;$("sheetUrl").value="";$("mappingBox").hidden=true;$("importBug").disabled=true;setStatus(WRITE_AUTHORIZED?"先输入目标表格 URL，再读取表头。读取后点击“直接更新并提单”即可写入。":"本次未获得提单授权，当前仅可读取和预览表头，不会写入。",WRITE_AUTHORIZED?"":"error");$("modalBackdrop").classList.add("open");setTimeout(()=>$("sheetUrl").focus(),0);}
const _openModal=openModal;
openModal=function(keys){_openModal(keys);if(selectedCases.length){$("modalSub").textContent=selectedCases.length===1?`${selected.key} · ${displayBug(selected)?.title||selected.content}`:`已选择 ${selectedCases.length} 条用例，将批量导入 Bug 表格`;renderBugPreview();setStatus(WRITE_AUTHORIZED?"先核对下方缺陷文案，再输入目标表格 URL 读取表头。待复核记录只可预览，不能提单。":"本次未获得提单授权，当前仅可读取和预览，不会写入。",WRITE_AUTHORIZED?"":"error");}};
function closeModal(){$("modalBackdrop").classList.remove("open");if(lastFocused&&typeof lastFocused.focus==="function")lastFocused.focus();}
function cleanText(value){return text(value).replace(/\\r\\n/g,"\n").replace(/\\n/g,"\n").replace(/\\r/g,"\n").replace(/\[(?:expected|actual|oracle|result)\]\s*/gi,"").trim();}
function cleanInline(value){return cleanText(value).replace(/\s*\n\s*/g," ");}
function codexModuleName(value){let name=String(value??"").trim();if(name.startsWith("【Codex-")&&name.endsWith("】"))name=name.slice(7,-1).trim();name=name.replace(/^[\s✅☑✔✓\uFE0F]+/u,"").trim();return name?"【Codex-"+name+"】":"";}
function numberedSteps(value){const lines=cleanText(value).split(/\n+/).map(line=>line.trim()).filter(Boolean);return lines.map((line,index)=>`${index+1}、${line.replace(/^\d+[、.)]\s*/,"")}`).join("\n");}
function cleanOutcome(value){return cleanText(value).replace(/^测试通过（静态）$/,"测试通过").replace(/^测试通过（自动化）$/,"测试通过");}
const STATIC_PREFIX="【静态检测】";const BUG_VERSION="Codex";function withStaticPrefix(value){const valueText=cleanText(value);return valueText?(valueText.startsWith(STATIC_PREFIX)?valueText:STATIC_PREFIX+valueText):"";}
function standardValue(header,c){
 const h=header.toLowerCase().replace(/[\s_：:]/g,"");const b=c.bug||{};
 const aliases=[["标题",["标题","问题","bug标题","缺陷标题"]],["缺陷描述",["缺陷描述","缺陷说明","问题描述"]],["前置条件",["前置条件","前置步骤","前置准备"]],["重现步骤",["重现步骤","复现步骤","操作步骤","步骤"]],["预期结果",["预期结果","期望结果","期望描述","预期正确表现"]],["实际结果",["实际结果","实际表现","当前错误表现","异常表现","现象"]],["需求模块",["需求模块","模块","功能模块","所属模块"]],["测试结果",["测试结果","状态"]],["缺陷状态",["缺陷状态","bug状态"]],["检测依据",["检测依据","代码依据"]],["自动化执行情况",["自动化执行情况","自动化结果"]],["真实环境残留",["真实环境残留","外部残留"]],["基线",["基线","分支"]],["版本号",["版本号","版本"]],["问题类型",["问题类型"]],["日志信息",["日志信息","日志"]],["验收备注",["验收备注"]]];
 const values={标题:cleanInline(b.title),缺陷描述:withStaticPrefix(b.description),前置条件:cleanText(b.precondition),重现步骤:cleanText(b.steps),预期结果:cleanText(b.expected),实际结果:cleanText(b.actual),需求模块:codexModuleName(cleanInline(c.module)),测试结果:cleanOutcome(c.result),缺陷状态:"未解决",检测依据:cleanText(b.evidence),自动化执行情况:cleanText(b.verification),真实环境残留:cleanText(c.residual),基线:cleanInline(REPORT.baseline),版本号:BUG_VERSION,问题类型:"BUG缺陷",日志信息:cleanText(b.evidence),验收备注:""};
 for(const [key,names] of aliases)if(names.some(n=>h===n.toLowerCase().replace(/[\s_：:]/g,"")))return values[key]??"";return "";
}
function validateBugSelection(){const errors=selectedCases.flatMap(c=>c.bug?.ready?[]:[`${c.key}：${(c.bug?.errors||["缺少完整缺陷文案"]).join("；")}`]);if(errors.length)throw new Error("无法提单，请先补齐缺陷内容：\n"+errors.join("\n"));}
function bugPreview(c){
 const b=c.bug||{};const fields=[["前置条件",b.precondition],["操作步骤",b.steps],["当前错误表现",b.actual],["预期正确表现",b.expected]];
 return `<article class="bug-preview${b.ready?"":" blocked"}"><div class="bug-preview-head"><strong>${escapeHtml(b.title||c.content||c.key)}</strong><span class="copy-badge">${b.ready?"缺陷文案":"待复核，不能提单"}</span></div><dl>${fields.map(([label,value])=>`<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value||"待补充")}</dd>`).join("")}</dl>${!b.ready?`<p class="preview-warning">${escapeHtml((b.errors||["缺少完整缺陷文案"]).join("；"))}</p>`:""}</article>`;
}
function renderBugPreview(){$("bugPreview").innerHTML=selectedCases.map(bugPreview).join("");}
function showMapping(headers,rows){$("mappingBox").hidden=false;$("mappingBox").innerHTML=`<table><thead><tr><th>用例</th>${headers.map(h=>`<th>${escapeHtml(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((row,index)=>`<tr><th>${escapeHtml(selectedCases[index].key)}</th>${row.map(value=>`<td>${escapeHtml(value)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;}
async function responseError(response,prefix){let detail="",payload={};try{payload=await response.clone().json();detail=payload.error||payload.message||"";}catch(_){try{detail=(await response.clone().text()).trim();}catch(__){}}const error=new Error(`${prefix} HTTP ${response.status}${detail?`：${detail}`:""}`);for(const key of ["submitted","total","batches"]){const value=Number(payload[key]);if(Number.isFinite(value))error[key]=value;}return error;}
async function readRemote(url){if(BRIDGE){const r=await fetch(BRIDGE.replace(/\/$/,"")+"/schema?url="+encodeURIComponent(url),{credentials:"omit",headers:{Accept:"application/json"}});if(!r.ok)throw await responseError(r,"桥接读取失败");const data=await r.json();if(data.ok===false)throw new Error(data.error||"桥接读取失败");return data;}const r=await fetch(url,{credentials:"include",headers:{Accept:"application/json,text/html,text/plain"}});if(!r.ok)throw await responseError(r,"读取失败");const ct=r.headers.get("content-type")||"";if(ct.includes("json"))return await r.json();const raw=await r.text();const doc=new DOMParser().parseFromString(raw,"text/html");const table=doc.querySelector("table");if(!table)throw new Error("URL 未返回 JSON 或 HTML table；跨域或表格 API 不可直接读取，请配置桥接地址。");return {headers:[...table.querySelectorAll("thead th")].map(x=>x.textContent.trim()),format:"html"};}
$("readHeaders").addEventListener("click",async()=>{const url=$("sheetUrl").value.trim();if(!/^https?:\/\//i.test(url)){setStatus("URL 必须以 http:// 或 https:// 开头。","error");return;}setStatus("正在读取目标表头...");try{const data=await readRemote(url);const headers=(data.headers||data.columns||[]).map(text).filter(Boolean);if(!headers.length)throw new Error("目标表格没有可识别的表头。");const rows=selectedCases.map(c=>headers.map(h=>standardValue(h,c)));remote={url,headers,rows};showMapping(headers,rows);const blocked=selectedCases.filter(c=>!c.bug?.ready).length;$("importBug").disabled=!WRITE_AUTHORIZED||blocked>0;setStatus(blocked?`已读取 ${headers.length} 个表头，但有 ${blocked} 条记录待复核，不能提单。`:(WRITE_AUTHORIZED?`已读取 ${headers.length} 个表头，将导入 ${rows.length} 条用例。核对映射后点击“直接更新并提单”即可写入。`:`已读取 ${headers.length} 个表头。当前未授权写入，仅展示映射预览。`),blocked||!WRITE_AUTHORIZED?"error":"success");}catch(e){remote=null;$("importBug").disabled=true;setStatus(e.message+" 未发生任何写入。","error");}});
$("importBug").addEventListener("click",async()=>{if(!WRITE_AUTHORIZED){setStatus("本次未获得提单授权，未发生任何写入。","error");return;}if(!remote||!selectedCases.length)return;setStatus("正在更新表头并批量导入...");try{validateBugSelection();remote.rows=selectedCases.map(c=>remote.headers.map(h=>standardValue(h,c)));const endpoint=BRIDGE?BRIDGE.replace(/\/$/,"")+"/import":remote.url;const r=await fetch(endpoint,{method:"POST",credentials:BRIDGE?"omit":"include",headers:{"Content-Type":"application/json",Accept:"application/json"},body:JSON.stringify({url:remote.url,headers:remote.headers,row:remote.rows[0],rows:remote.rows,caseKey:selectedCases[0].key,caseKeys:selectedCases.map(c=>c.key),sourceReport:REPORT.title})});if(!r.ok)throw await responseError(r,"导入失败");const data=await r.json();if(data.ok===false)throw new Error(data.error||"导入接口返回失败");const submitted=Number.isFinite(Number(data.submitted))?Number(data.submitted):remote.rows.length;const batches=Number.isFinite(Number(data.batches))?Number(data.batches):1;setStatus(`导入成功，已提交 ${submitted} 条用例（${batches} 批），目标接口已返回 2xx。`,"success");}catch(e){const progress=Number.isFinite(Number(e.submitted))&&Number.isFinite(Number(e.total))?`已提交 ${e.submitted}/${e.total} 条。 `:"";setStatus(progress+e.message+" 未能确认全部写入成功；未将本次操作标记为成功。","error");}});
$("closeModal").addEventListener("click",closeModal);$("modalBackdrop").addEventListener("click",e=>{if(e.target.id==="modalBackdrop")closeModal();});
$("newBug").addEventListener("click",openNewBug);$("selectVisible").addEventListener("click",toggleVisibleSelection);$("selectAllVisible").addEventListener("change",toggleVisibleSelection);document.addEventListener("keydown",e=>{if(e.key==="Escape"&&$("modalBackdrop").classList.contains("open"))closeModal();});
for(const id of ["search","resultFilter","moduleFilter","residualOnly"])$(id).addEventListener(id==="search"?"input":"change",render);
$("exportVisible").addEventListener("click",()=>{const blob=new Blob([JSON.stringify(visible,null,2)],{type:"application/json"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="filtered-test-results.json";a.click();URL.revokeObjectURL(a.href);});
$("writeHint").textContent=WRITE_AUTHORIZED?"本次已获提单授权：粘贴 URL、读取表头后可直接更新并提单。":"本次未获提单授权：HTML 仅可浏览和预览映射，不会写入。";
buildOptions();renderSummary();renderEvidence();render();
</script>
</body></html>'''


def generate(manifest_path: Path, review_path: Path, validated_path: Path, output: Path, title: str, bridge: str, write_authorized: bool = False):
    manifest, review, validated = map(load_json, [manifest_path, review_path, validated_path])
    if not validated.get("root"):
        raise ValueError("validated report lacks source coverage/root; rerun validate_report.py")
    checked = validate(manifest, review, Path(validated["root"]))
    if checked != validated:
        raise ValueError("stale/changed validation summary; rerun validate_report.py")
    cases = build_cases(manifest, review, validated)
    coverage = validated["source_coverage"]
    partial = validated["report_stage"] == "partial" or coverage["status"] != "complete"
    media = "；".join(f"{kind}：已读 {item['read']}/{item['total']}" for kind, item in coverage["media"].items())
    ledger_ref = manifest.get("source_coverage", {}).get("path", "source-coverage.json")
    ledger_path = Path(ledger_ref)
    if not ledger_path.is_absolute():
        ledger_path = Path(validated["root"]) / ledger_path
    ledger = load_json(ledger_path) if ledger_path.is_file() else {}
    sources = ledger.get("sources", [])
    snapshot_read = sum(bool(source.get("snapshot")) for source in sources)
    complete_sources = coverage["read_sources"]
    note = "阶段结果：资料或覆盖存在缺口，仅代表已审用例。" if partial else "资料与已登记规则已完成对账；此校验不替代需求语义审阅。"
    gaps = "".join(f"<li>{html.escape(gap)}</li>" for gap in coverage["gaps"])
    image = coverage["media"].get("image", {"read": 0, "total": 0})
    video = coverage["media"].get("video", {"read": 0, "total": 0})
    gaps_panel = ""
    if gaps:
        gaps_panel = (f'<details class="coverage-gaps"><summary>查看来源缺口（{len(coverage["gaps"])} 项）</summary>'
                      f'<ul>{gaps}</ul></details>')
    banner = (f'<section class="panel" id="sourceCoverage" role="status">'
              f'<div class="coverage-head"><div><strong>{html.escape(note)}</strong>'
              f'<p class="coverage-note">“正文快照已读”表示已获取需求正文；“证据完整闭合”还要求来源媒体逐项完成审查。</p></div>'
              f'<span class="chip {"pending" if partial else "pass"}">{"阶段结果 · partial" if partial else "完整"}</span></div>'
              f'<div class="coverage-grid">'
              f'<div class="coverage-stat neutral"><b>{snapshot_read}/{coverage["sources"]}</b><span>正文快照已读</span></div>'
              f'<div class="coverage-stat {"warn" if complete_sources < coverage["sources"] else "good"}"><b>{complete_sources}/{coverage["sources"]}</b><span>证据完整闭合</span></div>'
              f'<div class="coverage-stat {"good" if image["read"] == image["total"] else "warn"}"><b>{image["read"]}/{image["total"]}</b><span>图片已读</span></div>'
              f'<div class="coverage-stat {"good" if video["read"] == video["total"] else "warn"}"><b>{video["read"]}/{video["total"]}</b><span>视频已读</span></div>'
              f'</div>'
              f'{gaps_panel}'
              f'</section>')
    payload = {
        "title": title,
        "baseline": validated.get("baseline", review.get("baseline", "未记录")),
        "scope": validated.get("scope", review.get("scope", "code")),
        "counts": validated.get("counts", {}),
        "evidence": review.get("evidence", []),
        "report_stage": validated["report_stage"],
        "source_coverage": coverage,
        "write_authorized": bool(write_authorized),
        "cases": cases,
    }
    document = HTML_TEMPLATE.replace("__TITLE__", html.escape(title)).replace(
        "__BASELINE__", html.escape(str(payload["baseline"]))
    ).replace("__SCOPE__", html.escape(str(payload["scope"]))).replace(
        "__DATA__", esc_script(payload)
    ).replace("__COVERAGE__", banner).replace(
        "__BRIDGE__", esc_script(bridge or "")).replace(
        "__WRITE_AUTHORIZED__", "true" if write_authorized else "false"
    )
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing HTML: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")
    return len(cases)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="input-manifest.json")
    parser.add_argument("--review", required=True, type=Path, help="review.json")
    parser.add_argument("--validated", required=True, type=Path, help="validated-results.json")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--title", default="测试结果报告")
    parser.add_argument("--bridge", default="", help="Optional local bridge base URL")
    parser.add_argument(
        "--write-authorized",
        action="store_true",
        help="Enable direct bug-sheet writes only after explicit user authorization during the skill run",
    )
    args = parser.parse_args(argv)
    try:
        count = generate(
            args.input,
            args.review,
            args.validated,
            args.output,
            args.title,
            args.bridge,
            args.write_authorized,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"HTML_REPORT_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"output": str(args.output), "cases": count}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
