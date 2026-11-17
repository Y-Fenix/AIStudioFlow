#!/usr/bin/env python3
"""Validate current evidence and browser-check the default portable report delivery.

Does not discover or test product behavior. Run only after the host agent has
consumed the continuation queue. Exit 2 preserves an honest incomplete report;
it never turns a solver timeout or a geometry risk into a pass.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from export_portable_report import build_viewer, export_bundle, load_run
from portable_delivery import FORMAT, snapshot, verify_receipt

from audit_completion import CONFIRMED, completion
from merge_domain_audits import validate_baselines
from render_report import render, require, validate
from bug_register import build_register, register_csv
from quality_gate import build_quality_gate
import cross_repo

SKILL = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def inside(root, name):
    path = (root / name).resolve()
    require(path.is_relative_to(root.resolve()), "路径越出允许目录：" + str(name))
    return path


def verify_cross_repo(data, root, evidence):
    if 'cross_repo' not in data:
        return None
    refs = data['cross_repo']
    require(isinstance(refs, dict) and refs.get('baseline'), '跨库证据缺快照摘要')
    result = cross_repo.binding({'cross_repo': refs},
                                {'cross_repo': refs, 'baseline': refs['baseline']}, root)
    snap_path = Path(refs['snapshot']['path'])
    snap = read(snap_path if snap_path.is_absolute() else root / snap_path)
    client = snap['repositories'].get('client', {})
    require(result['project'] == 'gagasort' and result['run_id'] == data['baseline']['run_id'],
            '跨库证据不是本项目本轮')
    require(client.get('root') == str(root) and client.get('head') == data['baseline']['head'],
            '跨库客户端与巡检基线不同')
    save(evidence / 'cross-repo-validation.json', result)
    return result


def apply_cross_repo_completion(queue, cross):
    if cross is None:
        return
    pending = sum(cross['counts'].get(k, 0) for k in ('unreviewed', 'blocked'))
    queue['summary']['cross_repo_pending_assertions'] = pending
    if pending:
        queue['ready_for_final'] = False
        queue['tasks'].append({'id': 'CROSS-REPO-PENDING', 'agent': '总控', 'kind': 'cross_repo',
                               'reasons': ['跨库断言仍未闭合'],
                               'action': '按跨库账本 ID 续查依赖、调用双方及最终消费者，不转人工。',
                               'baseline': cross['baseline'], 'pending_assertions': pending})
        queue.setdefault('batches', []).append({'agent': '总控', 'task_ids': ['CROSS-REPO-PENDING']})
        queue['summary']['pending_tasks'] = len(queue['tasks'])


def verify_execution_receipts(data, root, evidence):
    """A log's existence alone cannot prove it was produced for this run."""
    baseline = data["baseline"]
    receipts = set()
    for run in data["suites"] + data.get("additional_runs", []):
        if run.get("status", "").startswith("未执行"):
            continue
        name = run.get("execution_receipt")
        require(bool(name), run["id"] + " 缺本轮执行回执；不能用已有日志代替本轮运行")
        require(name not in receipts, "多条执行记录复用了同一回执：" + name)
        receipts.add(name)
        receipt = read(inside(evidence, name))
        require(receipt["run_id"] == run["id"] and receipt["baseline_run_id"] == baseline["run_id"],
                run["id"] + " 执行回执不属于本轮")
        require(receipt["head_before"] == receipt["head_after"] == baseline["head"], run["id"] + " 执行期间 HEAD 不一致")
        timed_out = (receipt["state"] == "unknown" and receipt["exit_code"] == 124
                     and any(word in run.get("status", "") for word in ("超时", "受阻")))
        blocked = ("受阻" in run.get("status", "") and receipt["state"] == "finished"
                   and run.get("exit_code") not in (None, 0))
        require((receipt["state"] == "finished" or timed_out)
                and not receipt["changed_inputs"]
                and (not receipt.get("missing_outputs") or blocked),
                run["id"] + " 执行未结束、输入期间变化或产物缺失")
        require(receipt["command"] == run["command"] and receipt["exit_code"] == run["exit_code"],
                run["id"] + " 命令或退出码与执行回执不同")
        require(not (run["exit_code"] != 0 and "通过" in run.get("status", "") and "不通过" not in run["status"]),
                run["id"] + " 非零退出码不能标通过")
        log = inside(evidence, run["evidence"])
        require(log == inside(evidence, receipt["log"]) and digest(log) == receipt["log_sha256"], run["id"] + " 日志内容变化")
        require(bool(receipt["inputs"]), run["id"] + " 缺实际输入/生产依赖")
        for path, expected in receipt["inputs"].items():
            require(digest(inside(root, path)) == expected, run["id"] + " 执行输入已变化：" + path)
        for path, expected in receipt.get("outputs", {}).items():
            require(digest(inside(evidence, path)) == expected, run["id"] + " 执行产物已变化：" + path)


def verify_evidence(data, root, evidence):
    """Check live files, including uncommitted changes, against reviewed bytes."""
    from audit_scope import validate_scope
    scope_check = validate_scope(data, root, evidence, require_full=True)
    save(evidence / "scope-check.json", scope_check)
    require(scope_check["ok"], "固定范围校验失败：" + "；".join(scope_check["errors"]))
    baseline = data["baseline"]
    profile = read(SKILL / "assets/delivery-profile.json")
    require(data["report_contract_version"] == profile["report_contract_version"], "报告契约版本不符")
    audit = data.get("agent_audit", {})
    require(audit.get("protocol") == profile["agent_protocol"], "缺本轮多 Agent 深审记录")
    require(Path(baseline["root"]).resolve() == root, "证据仓库与当前仓库不同，不能复用旧报告")
    require(git(root, "rev-parse", "--show-toplevel") == str(root), "--root 不是仓库根目录")
    require(git(root, "rev-parse", "HEAD") == baseline["head"], "HEAD 已变化，须复审")
    require(git(root, "branch", "--show-current") == baseline["branch"], "分支已变化，须复核基线")

    def submodules(text):
        # Preserve '+', '-' and 'U' state markers as well as the commit ID.
        return {line[1:].split()[1]: (line[0], line[1:].split()[0])
                for line in text.splitlines() if line.strip()}

    current_submodules = subprocess.check_output(["git", "submodule", "status"], cwd=root, text=True)
    require(submodules(current_submodules) == submodules(baseline["submodules"]), "子模块版本或初始化状态已变化")
    dossiers = [inside(evidence, name) for name in audit.get("dossiers", [])]
    require(bool(dossiers) and all(p.is_file() for p in dossiers), "专项 dossier 缺失")
    validate_baselines(dossiers, root)
    dossier_features, hashes = set(), {}
    for path in dossiers:
        obj = read(path)
        dossier_features.update(f["id"] for f in obj.get("features", []))
        for name, expected in obj["baseline"]["source_hashes"].items():
            inside(root, name)
            require(name not in hashes or hashes[name] == expected, "专项之间源码版本冲突：" + name)
            hashes[name] = expected
    require({f["id"] for f in data["features"]} <= dossier_features, "存在无专项 dossier 的功能")
    categories = {f["display"]["category"] for f in data["features"]}
    if data.get("level_audit", {}).get("pipeline_version") == 2:
        categories.add("关卡")
    require(categories == {"玩法", "关卡", "系统", "配置", "埋点"},
            "全量巡检缺五类功能之一")
    require(any(f["display"]["category"] == "系统" and "多语言" in
                (f["display"]["group"] + f["display"]["name"]) for f in data["features"]), "系统缺多语言专项")
    for feature in data["features"]:
        require(feature.get("static_audit", {}).get("depth", {}).get("protocol") == profile["depth_protocol"],
                feature["id"] + " 缺 deep-v2 分支账本")

    traces, checked = set(), set()

    def check_source(name):
        if name not in checked:
            live = inside(root, name)
            snapshot = inside(evidence, "sources/" + name + ".txt")
            require(live.is_file() and snapshot.is_file() and digest(live) == digest(snapshot),
                    "源码与审查快照不一致：" + name)
            checked.add(name)

    def walk(value):
        if isinstance(value, dict):
            if "path" in value and "line" in value:
                name = value["path"]
                check_source(name)
                lines = len(inside(root, name).read_text(encoding="utf-8").splitlines())
                require(0 < value["line"] <= value.get("end_line", value["line"]) <= lines,
                        "源码行号越界：" + name)
                traces.add(name)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for kind in ("features", "findings", "configuration_groups"):
        walk(data.get(kind, []))
        for owner in data.get(kind, []):
            for name in owner.get("source_paths", []):
                check_source(name)
    validate(data, evidence)
    return dict(head=baseline["head"], branch=baseline["branch"], dossier_source_files=len(hashes),
                trace_source_files=len(traces), source_hash_mismatches=[], submodule_commits_match=True,
                feature_count=len(data["features"]),
                complete_features=sum(f["static_audit"]["status"] == "已完成" for f in data["features"]),
                findings=len({f["id"] for f in data["findings"] if f.get("kind") in CONFIRMED}),
                case_count=sum(len(f["static_audit"]["cases"]) for f in data["features"]),
                workflow_version=profile["workflow_version"],
                scope="证据一致性；不代替业务正确性或设备验收")


def cell(value):
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else "" if value is None else str(value)


def export_results(data, out):
    (out / 'bugs.csv').write_bytes(register_csv(build_register(data['findings'])).encode('utf-8'))

    def table(name, columns, rows):
        with (out / name).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(columns)
            writer.writerows([[cell(v) for v in row] for row in rows])

    rows = []
    for feature in data["features"]:
        display = feature["display"]
        for case in feature["static_audit"]["cases"]:
            rows.append([display["category"], display["group"], display["name"], feature["id"], case["id"],
                         case["dimension"], case["scenario"], case.get("preconditions"), case.get("input"),
                         case.get("expected"), case.get("actual"), case["verdict"], case.get("finding_ids", []),
                         ";".join(t["path"] + ":" + str(t["line"]) for t in case.get("trace", []))])
    table("coverage.csv", ["大类", "分组", "功能", "功能ID", "场景ID", "维度", "检查内容", "前置", "输入",
                           "预期", "实际", "结论", "关联问题", "源码"], rows)
    table("installation.csv", ["分类", "功能", "功能ID", "保留本地覆盖安装", "清本地同身份恢复", "清本地新身份"],
          [[f["display"]["category"], f["display"]["name"], f["id"], f["installation"]["upgrade"],
            f["installation"]["same_identity"], f["installation"]["new_identity"]] for f in data["features"]])
    table("configuration.csv", ["实例序号", "检查项", "输入", "结果", "证据", "边界"],
          [[i + 1, c.get("display_name", c.get("name")), c.get("input"), c.get("status"), c.get("evidence"),
            c.get("limits")] for i, c in enumerate(data["configuration_cases"])])
    lines = ["# 本轮问题明细", "", data["presentation"]["conclusion"], ""]
    for finding in data["findings"]:
        lines += ["## " + finding["id"] + " " + finding["display"]["title"], ""]
        for key, label in [("kind", "证据层级"), ("status", "状态"), ("condition", "触发条件"),
                           ("impact", "影响"), ("cause", "原因"), ("expected", "预期"), ("actual", "实际")]:
            lines.append("- " + label + "：" + cell(finding.get(key)))
        lines += ["", "白盒复核步骤：", ""]
        steps = (finding["display"].get("whitebox_steps") or finding.get("local_steps")
                 or finding.get("static_proof", {}).get("steps", []))
        lines += [str(i + 1) + ". " + cell(step) for i, step in enumerate(steps)]
        if finding.get("manual"):
            lines += ["", "黑盒路线（执行状态：" + cell(finding["manual"].get("status")) + "）：", "",
                      cell(finding["manual"])]
        lines += ["", "日志：" + cell(finding.get("log")), "范围限制：" + cell(finding.get("missing")), ""]
    (out / "findings.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    counts = {key: sum(f["display"]["category"] == key for f in data["features"])
              for key in ("玩法", "关卡", "系统", "配置", "埋点")}
    confirmed = len({f["id"] for f in data["findings"] if f.get("kind") in CONFIRMED})
    summary = ["# GagaSort 本轮静态巡检", "", data["presentation"]["conclusion"], "",
               "- 基线：" + data["baseline"]["head"], "- 分支：" + data["baseline"]["branch"],
               "- 纳入功能：" + cell(counts), "- 已确认问题：" + str(confirmed),
               "- 功能场景：" + str(len(rows)), "- 配置字段：" + str(len(data["configuration_fields"])),
               "- 配置输入/展示记录：" + str(len(data["configuration_cases"])),
               "- 执行记录：" + str(len(data["suites"]) + len(data.get("additional_runs", []))), "",
               data["level_audit"]["solvability"]["summary"], data["level_audit"]["visual"]["summary"], "",
               "执行范围：" + data["presentation"]["execution_scope"],
               "未执行范围：" + data["presentation"]["not_executed"], "",
               "报告交互校验、执行完成度和业务缺陷数量分别查看 delivery-check.json。"]
    (out / "audit.md").write_text("\n".join(summary) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--node", help="Node 可执行路径；默认读取 PATH")
    parser.add_argument("--browser", help="Chrome/Chromium 可执行路径；默认自动发现")
    parser.add_argument("--legacy-html", action="store_true", help="仅明确需要旧联机格式时使用；非默认交付")
    args = parser.parse_args()
    root, out = args.root.resolve(), args.evidence_dir.resolve()
    require(out.is_dir() and out.is_relative_to(root / "QA/results"), "必须使用本仓库 QA/results 下的本轮目录")
    # Invalidate an earlier success before any check; failures must never leave a stale green receipt.
    delivery = dict(status="检查中", report_ready=False, audit_complete=False,
                    scope="报告与证据交付校验，不是新的游戏测试")
    save(out / "delivery-check.json", delivery)
    try:
        data = read(out / "report-data.json")
        cross = verify_cross_repo(data, root, out)
        result = verify_evidence(data, root, out)
        verify_execution_receipts(data, root, out)
        queue = completion(data, root, out)
        apply_cross_repo_completion(queue, cross)
        save(out / "continuation.json", queue)
        require(queue["ready_for_final"] or data["presentation"]["overall"] == "执行不完整",
                "存在未完成检查时必须明确执行不完整，不能报全量通过")
        quality = build_quality_gate(data, queue, out)
        data["quality_gate"] = quality
        save(out / "quality-gate.json", quality)
        export_results(data, out)
        node = args.node or shutil.which("node")
        require(bool(node), "缺 Node；Agent 使用宿主依赖发现入口补齐后自动重试")
        if args.legacy_html:
            manifest = render(data, out, out / "report.html", SKILL / "assets/report-template.html")
            require(digest(out / "report.html") == manifest["sha256"], "HTML 与生成清单不一致")
            result.update(html_manifest_match=True, template_unchanged=True)
            command = [str(node), str(SKILL / "scripts/check_report.cjs"), "--report", str(out / "report.html"),
                       "--output-dir", str(out)]
            if args.browser:
                command += ["--browser", args.browser]
            receipt_path = out / "html-interaction-check.json"
        else:
            stage = Path(tempfile.mkdtemp(prefix="portable-delivery-", dir=out))
            viewer, bundle = stage / "查看报告.html", stage / "batch"
            viewer.write_text(build_viewer(), encoding="utf-8")
            view, csv_raw, reader = load_run(out, data)
            export_bundle(view, csv_raw, reader, bundle,
                          "本报告来自所列批次的静态检查；完成度、执行状态与范围限制以本轮结论为准。")
            manifest = dict(format=FORMAT, files=snapshot(viewer, bundle),
                            directory=stage.relative_to(out).as_posix(),
                            report_data_sha256=digest(out / "report-data.json"),
                            workflow_version=result["workflow_version"])
            save(out / "portable-manifest.json", manifest)
            receipt_path = out / "portable-interaction-check.json"
            command = [str(node), str(SKILL / "scripts/check_portable_report.cjs"), str(viewer), str(bundle),
                       args.browser or "", str(receipt_path)]
            result.update(portable_manifest_match=True, template_unchanged=True)
        # Never let an earlier success receipt stand in for a failed new browser run.
        receipt_path.unlink(missing_ok=True)
        save(out / "final-evidence-check.json", result)
        env = os.environ.copy()
        node_path = Path(node).resolve().parent.parent / "node_modules"
        if node_path.is_dir():
            existing = env.get("NODE_PATH")
            env["NODE_PATH"] = str(node_path) if not existing else str(node_path) + os.pathsep + existing
        with (out / "html-interaction.log").open("w", encoding="utf-8") as stream:
            stream.write("Command: " + cell(command) + "\n")
            stream.flush()
            process = subprocess.run(command, cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=180)
        require(process.returncode == 0, "HTML 交互未通过，详见 html-interaction.log；由 Agent 修复，不转人工")
        ui = read(receipt_path)
        if args.legacy_html:
            require(ui.get("status") == "passed" and ui.get("report_sha256") == digest(out / "report.html"),
                    "交互回执不是本次 HTML")
            artifact = dict(format="legacy-html", report_sha256=manifest["sha256"])
        else:
            verify_receipt(ui, viewer, bundle)
            require(snapshot(viewer, bundle) == manifest["files"], "便携产物与生成清单不一致")
            require(manifest["report_data_sha256"] == digest(out / "report-data.json"), "交互期间报告数据变化")
            artifact = dict(format=FORMAT, portable_directory=manifest["directory"],
                            portable_manifest_sha256=digest(out / "portable-manifest.json"),
                            interaction_receipt_sha256=digest(receipt_path),
                            viewer_sha256=manifest["files"]["viewer"])
        # Recheck at the end too: live code can change while the browser is running.
        verify_evidence(data, root, out)
        verify_cross_repo(data, root, out)
        verify_execution_receipts(data, root, out)
        delivery.update(status="交付校验通过" if queue["ready_for_final"] else "报告已验证，巡检仍有未完成项",
                        report_ready=True, audit_complete=queue["ready_for_final"],
                        pending_tasks=queue["tasks"], **artifact,
                        counts=queue["summary"], quality_gate=quality, ui_assertions=len(ui["checks"]),
                        workflow_version=result["workflow_version"])
        quality.update(report_ready=True, **artifact, html_interaction_passed=True)
        save(out / "quality-gate.json", quality)
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
        delivery.update(status="交付校验失败", reason=str(exc))
    save(out / "delivery-check.json", delivery)
    print(json.dumps(delivery, ensure_ascii=False))
    return 0 if delivery["report_ready"] and delivery["audit_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
