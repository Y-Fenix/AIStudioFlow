#!/usr/bin/env python3
"""Merge independent static audit dossiers into a v2.1 report.

This script treats the base report as a feature inventory only. It never uses
the base report's static conclusions as current evidence. Every current
conclusion must come from a domain dossier or remains amber/incomplete.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from audit_completion import completion
from audit_scope import manifest, target_gaps, validate_scope

DIMENSIONS = [
    "入口与正常链路", "边界与异常", "重复与异步", "状态与持久化",
    "配置变化", "升级与重装", "跨模块影响",
]
DEPTH_STATUSES = {"已闭合", "部分闭合", "未检查", "不适用"}
TOPIC_DIMENSION = {
    "入口": "入口与正常链路", "正常": "入口与正常链路", "序列": "入口与正常链路",
    "边界": "边界与异常", "异常": "边界与异常", "失败": "边界与异常", "配置": "配置变化",
    "重复": "重复与异步", "回调": "重复与异步", "关闭": "重复与异步", "异步": "重复与异步",
    "恢复": "状态与持久化", "存档": "状态与持久化", "领取": "状态与持久化", "履约": "状态与持久化",
    "升级": "升级与重装", "安装": "升级与重装", "例外": "跨模块影响", "跨": "跨模块影响",
}


def dim_for(topic: str) -> str:
    for key, value in TOPIC_DIMENSION.items():
        if key in topic:
            return value
    return "跨模块影响"


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def finding_verdict(finding_ids: list[str], issue_kinds: dict[str, str]) -> str:
    kinds = {issue_kinds.get(key) for key in finding_ids}
    for kind, verdict in (("产品问题已证", "发现产品问题"),
                          ("方法问题已证", "发现方法级问题"),
                          ("静态缺陷已证", "发现静态缺陷")):
        if kind in kinds:
            return verdict
    return "风险待确认"


def merge_record(existing: dict, incoming: dict, record_id: str) -> dict:
    """Merge complementary schema fields while rejecting contradictory facts."""
    conflicts = [key for key in existing.keys() & incoming.keys()
                 if existing[key] != incoming[key]]
    require(not conflicts, f"{record_id}: 同名记录字段冲突 {sorted(conflicts)}")
    return {**existing, **incoming}


def validate_dossier_feature(detail: dict, feature: dict) -> tuple[dict, dict, dict]:
    """Reject shallow dossiers before they can become report rows.

    The old merge path inferred dimensions from free-form topics and filled the
    rest with boilerplate cases. That made a thin inventory look like a deep
    review. v2 requires an explicit branch inventory, dimension ledger, and
    case-to-branch mapping for every feature.
    """
    tag = feature["id"]
    branches = detail.get("branches")
    coverage = detail.get("coverage")
    checks = detail.get("checks")
    require(isinstance(branches, list) and branches, f"{tag}: dossier缺少真实分支清单 branches")
    require(isinstance(coverage, list) and len(coverage) == len(DIMENSIONS),
            f"{tag}: dossier必须逐项提供七维 coverage")
    require(isinstance(checks, list) and checks, f"{tag}: dossier缺少逐场景 checks")

    branch_ids = set()
    branch_dims = {}
    for branch in branches:
        require(isinstance(branch, dict), f"{tag}: branch必须是对象")
        for key in ("id", "dimension", "condition", "consumer", "evidence"):
            require(branch.get(key) not in (None, "", []), f"{tag}: branch缺少{key}")
        require(branch["dimension"] in DIMENSIONS, f"{tag}: branch维度无效")
        require(branch["id"] not in branch_ids, f"{tag}: branch ID重复 {branch['id']}")
        require(isinstance(branch["evidence"], list) and branch["evidence"],
                f"{tag}/{branch['id']}: 缺分支源码证据")
        branch_ids.add(branch["id"])
        branch_dims[branch["id"]] = branch["dimension"]

    coverage_by_dim = {}
    covered_branch_ids = set()
    for row in coverage:
        require(isinstance(row, dict), f"{tag}: coverage必须是对象")
        for key in ("dimension", "status", "branch_ids", "case_ids"):
            require(key in row, f"{tag}: coverage缺少{key}")
        dim = row["dimension"]
        require(dim in DIMENSIONS and dim not in coverage_by_dim, f"{tag}: coverage维度无效或重复")
        require(row["status"] in DEPTH_STATUSES, f"{tag}/{dim}: coverage状态无效")
        require(isinstance(row["branch_ids"], list) and isinstance(row["case_ids"], list),
                f"{tag}/{dim}: branch_ids/case_ids必须是数组")
        require(set(row["branch_ids"]) <= branch_ids, f"{tag}/{dim}: 引用了不存在的branch")
        require(all(branch_dims[x] == dim for x in row["branch_ids"]),
                f"{tag}/{dim}: branch跨维度引用")
        if row["status"] == "已闭合":
            require(row["branch_ids"] and row["case_ids"], f"{tag}/{dim}: 已闭合但没有分支或场景")
        if row["status"] == "不适用":
            require(row.get("reason") and row.get("evidence"), f"{tag}/{dim}: 不适用必须有原因和证据")
        if row["status"] in {"部分闭合", "未检查"}:
            require(row.get("gap"), f"{tag}/{dim}: 未闭合必须写具体gap")
        coverage_by_dim[dim] = row
        covered_branch_ids.update(row["branch_ids"])
    require(set(coverage_by_dim) == set(DIMENSIONS), f"{tag}: coverage没有覆盖七个维度")
    require(covered_branch_ids == branch_ids, f"{tag}: 存在未归属到coverage的分支")

    case_ids = set()
    referenced_branches = set()
    referenced_findings = set()
    for check in checks:
        require(isinstance(check, dict), f"{tag}: check必须是对象")
        for key in ("case_id", "dimension", "topic", "scenario", "finding", "evidence", "branch_ids"):
            require(check.get(key) not in (None, "", []), f"{tag}: check缺少{key}")
        require(check["dimension"] in DIMENSIONS, f"{tag}/{check.get('case_id')}: 维度无效")
        require(check["case_id"] not in case_ids, f"{tag}: case_id重复 {check['case_id']}")
        require(isinstance(check["branch_ids"], list) and check["branch_ids"],
                f"{tag}/{check['case_id']}: 没有关联真实分支")
        require(set(check["branch_ids"]) <= branch_ids, f"{tag}/{check['case_id']}: 引用了不存在的branch")
        require(all(branch_dims[x] == check["dimension"] for x in check["branch_ids"]),
                f"{tag}/{check['case_id']}: 分支维度不一致")
        require(isinstance(check["evidence"], list) and check["evidence"],
                f"{tag}/{check['case_id']}: 缺场景源码证据")
        require("finding_ids" in check and isinstance(check["finding_ids"], list),
                f"{tag}/{check['case_id']}: finding_ids必须是数组，不能把功能问题泛挂到所有场景")
        require(set(check["finding_ids"]) <= set(feature.get("related_findings", [])),
                f"{tag}/{check['case_id']}: 引用了不属于本功能的问题")
        case_ids.add(check["case_id"])
        referenced_branches.update(check["branch_ids"])
        referenced_findings.update(check["finding_ids"])
    require(referenced_branches == branch_ids, f"{tag}: 存在分支没有被任何具体场景核对")
    require(referenced_findings == set(feature.get("related_findings", [])),
            f"{tag}: 存在功能问题没有回链到具体检查场景")
    referenced_cases = set()
    for row in coverage:
        require(set(row["case_ids"]) <= case_ids, f"{tag}/{row['dimension']}: 引用了不存在的case")
        referenced_cases.update(row["case_ids"])
        if row["branch_ids"]:
            require(row["case_ids"], f"{tag}/{row['dimension']}: 有真实分支却没有具体场景")
        if row["status"] == "已闭合":
            require(set(row["case_ids"]) and set(row["case_ids"]) <= case_ids,
                    f"{tag}/{row['dimension']}: 已闭合但没有有效场景")
    require(referenced_cases == case_ids, f"{tag}: 存在具体场景没有归属到coverage维度")
    return {"branches": branches, "coverage": coverage, "checks": checks}, coverage_by_dim, branch_dims


def snapshot(root: Path, evidence: Path, path: str) -> None:
    source = root / path
    if not source.is_file():
        return
    target = evidence / "sources" / (path + ".txt")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())


def trace_for(root: Path, evidence: Path, entries: list[dict], note: str) -> list[dict]:
    out = []
    for entry in entries:
        path = entry.get("path", "")
        source = root / path
        require(source.is_file(), f"源码证据不存在: {path}")
        snapshot(root, evidence, path)
        count = len(source.read_text(errors="replace").splitlines())
        line = int(entry.get("line", 0))
        end = int(entry.get("end_line", line))
        require(0 < line <= end <= count, f"源码证据行号无效: {path}:{line}-{end}")
        evidence_note = entry.get("note") or note
        out.append({"path": path, "line": line, "end_line": end,
                    "note": evidence_note})
    return out


def collect_dossiers(paths: list[Path], features: list[dict]) -> tuple[dict[str, tuple[dict, dict]], list[dict]]:
    """Collect feature records and findings from every specialist dossier."""
    feature_map = {feature["id"]: feature for feature in features}
    dossiers: dict[str, tuple[dict, dict]] = {}
    findings: dict[str, dict] = {}
    linked_findings: dict[str, set[str]] = {}
    for path in paths:
        obj = json.loads(path.read_text())
        for finding in obj.get("findings", []):
            finding_id = finding.get("id")
            require(finding_id, f"{path}: finding缺少id")
            if finding_id in findings:
                findings[finding_id] = merge_record(findings[finding_id], finding, finding_id)
            else:
                findings[finding_id] = finding
        for detail in obj.get("features", []):
            feature_id = detail["id"]
            require(feature_id in feature_map, f"{path}: dossier引用未知功能 {feature_id}")
            require(feature_id not in dossiers, f"功能重复出现在多个 dossier: {feature_id}")
            dossiers[feature_id] = (obj, detail)
            linked_findings.setdefault(feature_id, set()).update(detail.get("related_findings", []))

    finding_ids = set(findings)
    for feature_id, linked in linked_findings.items():
        missing = linked - finding_ids
        require(not missing, f"{feature_id}: dossier回链缺少finding记录 {sorted(missing)}")
        feature_map[feature_id]["related_findings"] = sorted(
            set(feature_map[feature_id].get("related_findings", [])) | linked)
    return dossiers, list(findings.values())


def validate_baselines(paths: list[Path], root: Path) -> None:
    """Do not stamp today's source snapshots onto yesterday's analysis."""
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    for path in paths:
        obj = json.loads(path.read_text())
        baseline = obj.get("baseline", {})
        require(baseline.get("head") == head, f"{path}: dossier HEAD与当前版本不一致，须续查")
        hashes = baseline.get("source_hashes", {})
        require(isinstance(hashes, dict) and hashes, f"{path}: 缺审查完成时的 baseline.source_hashes")
        referenced = set()
        for feature in obj.get("features", []):
            referenced.update(feature.get("source_paths", []))
            for row in feature.get("branches", []) + feature.get("coverage", []) + feature.get("checks", []):
                referenced.update(e["path"] for e in row.get("evidence", []))
        require(referenced <= hashes.keys(), f"{path}: 部分分支源码没有审查哈希 {sorted(referenced - hashes.keys())}")
        for source, expected in hashes.items():
            target = root / source
            require(target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == expected,
                    f"{path}: 审查后源码变化 {source}，须续查，不能仅刷新快照")


def apply_source_rechecks(feature: dict, detail: dict, baseline: dict) -> None:
    """Resolve inherited drift only with explicit current scenario evidence."""
    resolved = set()
    checks = {c["case_id"]: c for c in detail.get("checks", [])}
    for row in detail.get("source_rechecks", []):
        path = row["path"]
        ids = row.get("case_ids", [])
        require(path in baseline.get("source_hashes", {}), f"{path}: 变更复核缺当前源码哈希")
        require(ids and set(ids) <= checks.keys(), f"{path}: 变更复核缺具体场景")
        require(any(e.get("path") == path for cid in ids for e in checks[cid].get("evidence", [])),
                f"{path}: 复核场景没有引用变更路径")
        require(row.get("conclusion"), f"{path}: 缺变更及消费者复核结论")
        resolved.add(path)
    feature["source_drift"] = [p for p in feature.get("source_drift", []) if p not in resolved]
    feature["source_rechecks"] = detail.get("source_rechecks", [])


def case(feature: dict, check: dict, index: int, root: Path, evidence: Path,
         issue_ids: set[str], issue_kinds: dict[str, str]) -> dict:
    topic = str(check["topic"])
    finding = str(check["finding"])
    trace = trace_for(root, evidence, check.get("evidence", []), topic)
    linked = [x for x in check.get("finding_ids", []) if x in issue_ids and x in feature.get("related_findings", [])]
    confirmed = {"静态缺陷已证", "方法问题已证", "产品问题已证"}
    verdict = "发现问题" if any(issue_kinds.get(i) in confirmed for i in linked) else ("待核实" if linked else "未见问题")
    row = {
        "id": check["case_id"],
        "dimension": check["dimension"],
        "scenario": check["scenario"],
        "preconditions": check.get("preconditions", "当前 HEAD；专项 Agent 已核定入口和资格。"),
        "input": check.get("input", "按该场景记录的真实事件顺序核对。"),
        "basis": check.get("basis", "专项 Agent dossier 的规则和源码证据。"),
        "expected": check.get("expected", "满足业务不变量，非法状态不能越过门禁。"),
        "actual": finding,
        "verdict": verdict,
        "trace": trace,
        "branch_ids": list(check["branch_ids"]),
        "finding_ids": linked,
        "run_ids": [],
    }
    if verdict in {"未见问题", "发现问题"} and not trace:
        row["verdict"] = "未检查"
        row["reason"] = "专项记录没有可核对的当前源码快照。"
        row["finding_ids"] = []
    if verdict == "待核实":
        row["reason"] = "关联问题记录尚未达到已证门槛，保留为风险待核实。"
    return row


def missing_case(feature: dict, dimension: str, reason: str, index: int) -> dict:
    return {
        "id": f"{feature['id']}-agent-missing-{index:02d}",
        "dimension": dimension,
        "scenario": f"{feature['name']}：{dimension}",
        "preconditions": "当前 HEAD；需要该领域 Agent 的对应入口和消费者证据。",
        "input": "本轮没有把该维度当作已完成检查。",
        "basis": "专项 dossier 未提供该维度的闭合证据。",
        "expected": "需要沿真实分支核对输入、状态变化和最终消费者。",
        "actual": "当前只完成全项目功能盘点，不能据此判断通过。",
        "verdict": "未检查",
        "reason": reason,
        "trace": [], "finding_ids": [], "run_ids": [],
    }


def normalize_level_audit(data: dict, evidence: Path) -> None:
    """Keep execution-specific blockers in summaries, but use report-contract statuses.

    Level scanners may use ``自动化受阻`` as an execution state. The HTML contract
    intentionally has a smaller vocabulary; a blocked stage is therefore rendered
    as ``检查未完成`` while its summary and execution receipt retain the exact cause.
    """
    level = data.setdefault("level_audit", {})
    level.setdefault("pipeline_version", 2)
    level.setdefault("inventory_file", "levels/level-inventory.json")
    level.setdefault("run_ids", [])
    level.setdefault("anomalies", [])
    level.setdefault("risks", [])
    level.setdefault("samples", [])
    level.setdefault("table", [])
    inventory_file = evidence / level["inventory_file"]
    if not inventory_file.is_file():
        inventory_file.parent.mkdir(parents=True, exist_ok=True)
        inventory_file.write_text(json.dumps({
            "schema_version": 1,
            "scope": "本轮读取到的 Resources manifest 关卡集合",
            "status": "自动化受阻",
            "levels": [],
            "files": [],
            "failure": "本轮未建立逐关输入。",
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    allowed = {"未检查", "检查未完成", "检查完成未见问题", "发现问题"}
    for key, summary in (
        ("layout", "本轮未建立逐关输入，布局检查未完成。"),
        ("solvability", "本轮未建立逐关输入，求解检查未完成。"),
    ):
        entry = level.setdefault(key, {})
        if entry.get("status") not in allowed:
            # No inventory means the stage did not start. Keep that distinct from
            # a partially executed stage whose result file contains unresolved rows.
            entry["status"] = "未检查"
        entry.setdefault("summary", summary)
        entry.setdefault("total", 0)
        entry.setdefault("checked", 0)
        entry.setdefault("run_ids", list(level.get("run_ids", [])))
        entry.setdefault("evidence", [])
        entry.setdefault("result_file", f"levels/{key}-results.json")

    visual = level.setdefault("visual", {})
    if visual.get("status") not in allowed | {"有风险待确认"}:
        visual["status"] = "检查未完成"
    visual.setdefault("summary", "本轮未建立逐关输入，岸壁/水面网格与位置图检查未完成。")
    visual.setdefault("total", 0)
    visual.setdefault("checked", 0)
    visual.setdefault("run_ids", list(level.get("run_ids", [])))
    visual.setdefault("result_file", "levels/visual-summary.json")
    visual.setdefault("evidence", [])
    visual.setdefault("wall_risk_count", 0)
    visual.setdefault("water_risk_count", 0)
    visual_result = evidence / visual["result_file"]
    if not visual_result.is_file():
        visual_result.parent.mkdir(parents=True, exist_ok=True)
        visual_result.write_text(json.dumps({
            "schema_version": 1,
            "inventory": level["inventory_file"],
            "total": 0,
            "checked": 0,
            "results": [],
            "status": "自动化受阻",
            "summary": visual["summary"],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for entry in (level["layout"], level["solvability"], visual):
        result = entry.get("result_file")
        if result and result not in entry.setdefault("evidence", []):
            entry["evidence"].append(result)
    required_rows = {
        "structure": "关卡配置是否合法",
        "package": "关卡打包是否一致",
        "solver": "无道具能否通关",
        "wall": "岸壁是否重叠",
        "water": "水面是否折叠",
    }
    current_rows = {row.get("id"): row for row in level.get("summary_rows", [])}
    level["summary_rows"] = [
        current_rows.get(row_id, {
            "id": row_id,
            "name": name,
            "status": "检查未完成",
            "summary": "本轮未建立逐关输入，检查未完成。",
            "evidence": ["levels/level-inventory.json"],
        }) for row_id, name in required_rows.items()
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-data", type=Path, required=True)
    ap.add_argument("--evidence-dir", type=Path, required=True)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--dossier", type=Path, action="append", required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    data = json.loads(args.base_data.read_text())
    scope = validate_scope(data, args.root.resolve(), args.evidence_dir)
    require(scope["ok"], "固定范围校验失败：" + "；".join(scope["errors"]))
    fixed = {f["id"]: f for f in manifest()["features"]} if scope["mode"] == "full" else {}
    validate_baselines(args.dossier, args.root)
    dossiers, dossier_findings = collect_dossiers(args.dossier, data["features"])
    existing_findings = {x["id"]: x for x in data.get("findings", [])}
    for finding in dossier_findings:
        finding_id = finding["id"]
        if finding_id in existing_findings:
            existing_findings[finding_id] = merge_record(existing_findings[finding_id], finding, finding_id)
            for index, existing in enumerate(data["findings"]):
                if existing["id"] == finding_id:
                    data["findings"][index] = existing_findings[finding_id]
                    break
        else:
            data.setdefault("findings", []).append(finding)
            existing_findings[finding_id] = finding
    issue_ids = {x["id"] for x in data.get("findings", [])}
    issue_kinds = {x["id"]: x.get("kind", "") for x in data.get("findings", [])}
    deep = 0
    complete = 0
    for feature in data["features"]:
        item = dossiers.get(feature["id"])
        if not item:
            feature["static_audit"] = {"status": "未完成", "summary": "已盘点，尚未分配到专项 Agent 深审。", "cases": [missing_case(feature, d, "当前批次没有该功能的专项 dossier。", i + 1) for i, d in enumerate(DIMENSIONS)]}
            feature["assessment"].update(code_review="未审查", verdict="证据不足", code_conclusion="仅完成入口盘点，未完成专项代码审查。", conclusion="仅完成入口盘点，未完成专项代码审查。", follow_up="需要分配到对应专项 Agent 后再判断。", run_ids=[])
            if feature.get("source_drift"):
                feature["assessment"]["verdict"] = "当前版本待复审"
            continue
        dossier, detail = item
        depth, coverage_by_dim, _ = validate_dossier_feature(detail, feature)
        apply_source_rechecks(feature, detail, dossier["baseline"])
        # 将 dossier 中的分支/不适用证据也快照到本轮 evidence，避免报告只校验
        # checks 的证据而让深审账本指向无法复核的外部路径。
        for branch in depth["branches"]:
            branch["evidence"] = trace_for(
                args.root, args.evidence_dir, branch["evidence"], branch["condition"])
        for row in depth["coverage"]:
            if row["status"] == "不适用":
                row["evidence"] = trace_for(
                    args.root, args.evidence_dir, row["evidence"], row["reason"])
        deep += 1
        feature["audit_agent"] = dossier.get("agent", detail.get("scope", "专项 Agent"))
        feature["display"]["check_summary"] = detail.get("summary", feature["display"].get("check_summary", "专项静态检查"))
        cases = [case(feature, c, i + 1, args.root, args.evidence_dir, issue_ids, issue_kinds)
                 for i, c in enumerate(depth["checks"])]
        for merged_case, check in zip(cases, depth["checks"]):
            merged_case["scope_targets"] = check.get("scope_targets", [])
        for row in depth["coverage"]:
            if row["status"] in {"部分闭合", "未检查"}:
                cases.append(missing_case(feature, row["dimension"], row["gap"], len(cases) + 1))
            elif row["status"] == "不适用":
                cases.append({
                    "id": f"{feature['id']}-agent-na-{len(cases) + 1:02d}",
                    "dimension": row["dimension"],
                    "scenario": f"{feature['name']}：{row['dimension']}（不适用）",
                    "preconditions": "当前 HEAD；专项 Agent 已核定功能边界。",
                    "input": "核对该功能是否存在此维度的业务入口。",
                    "basis": row.get("reason", "专项 Agent 给出的不适用依据。"),
                    "expected": "该维度不属于本功能责任范围。",
                    "actual": row.get("reason", "经源码证据确认不适用。"),
                    "verdict": "不适用", "reason": row.get("reason", "不适用"),
                    "trace": trace_for(args.root, args.evidence_dir, row.get("evidence", []), row["dimension"]),
                    "finding_ids": [], "run_ids": [],
                })
        gaps = list(detail.get("gaps", []))
        if feature["id"] in fixed:
            gaps += target_gaps({"static_audit": {"cases": cases}}, fixed[feature["id"]])
        status = "已完成" if not gaps and all(x["verdict"] in {"未见问题", "发现问题", "不适用"} for x in cases) else "未完成"
        if status == "已完成":
            complete += 1
        summary = detail.get("summary", "专项 Agent 已提供检查记录。")
        if gaps:
            summary += " 未闭合：" + "；".join(gaps)
        feature["static_audit"] = {
            "status": status, "summary": summary, "cases": cases,
            "depth": {
                "protocol": "deep-v2",
                "coverage": depth["coverage"],
                "branches": depth["branches"],
            },
        }
        feature["gaps"] = gaps
        # Dossiers historically used external_checks for local run receipts.
        # Only entries with the report-contract id/assertion shape are external
        # facts; local receipts are already represented by suite/run_ids.
        feature["external_checks"] = [
            item for item in detail.get("external_checks", [])
            if isinstance(item, dict) and item.get("id") and item.get("assertion")
        ]
        feature["assessment"].update(
            code_review="完成静态审查" if status == "已完成" else "局部静态审查",
            code_conclusion=summary,
            conclusion=summary,
            verdict=finding_verdict(feature["related_findings"], issue_kinds) if feature.get("related_findings") else ("局部检查未见问题" if status == "已完成" else "证据不足"),
            follow_up="；".join(gaps) or "无专项缺口。",
            run_ids=[],
        )
        if feature.get("source_drift"):
            feature["assessment"]["verdict"] = "当前版本待复审"
        feature["installation"].update(detail.get("installation", {}))
    data["presentation"]["overall"] = "执行不完整"
    data["presentation"]["conclusion"] = (
        f"本轮采用专项 Agent 合并：已盘点 {len(data['features'])} 个功能，"
        f"完成专项深审 {deep} 个，其中静态七维闭合 {complete} 个；"
        "其余功能保留棕色未完成，不把盘点结果冒充通过。"
    )
    data["presentation"]["execution_scope"] += " 本轮新增玩法、关卡、系统、配置/存档专项 dossier 合并和证据质量门禁。"
    data["presentation"]["supplement_summary"] += " 功能清单来自本轮锁定范围；专项 Agent 未提供的维度均标为未检查。"
    # Bind every current execution record to its run-specific receipt when the
    # runner produced one. This keeps the delivery validator from accepting a
    # bare log as evidence while avoiding manual report-data edits.
    for run in data.get("suites", []) + data.get("additional_runs", []):
        if run.get("status", "").startswith("未执行") or run.get("execution_receipt"):
            continue
        receipt = args.evidence_dir / "execution" / run["id"] / "receipt.json"
        if receipt.is_file():
            run["execution_receipt"] = receipt.relative_to(args.evidence_dir).as_posix()
            receipt_data = json.loads(receipt.read_text(encoding="utf-8"))
            run["command"] = receipt_data["command"]
            run["evidence"] = receipt_data["log"]
            run["exit_code"] = receipt_data["exit_code"]
            if receipt_data["exit_code"] == 0 and run.get("status", "").startswith("自动化受阻"):
                run["status"] = "局部验证通过"
                run["reason"] = "退出码为 0，局部隔离验证完成；不扩展为真实设备、服务端或发布链路结论。"
            elif receipt_data["exit_code"] != 0 and run.get("status", "").startswith("局部验证通过"):
                run["status"] = "自动化受阻"
                run["reason"] = "退出码非零，保留为自动化受阻；不判定产品缺陷。"
    # 报告会内嵌所有声明的来源文件；盘点路径也必须快照，不能只快照深审 trace。
    for owner in data.get("features", []) + data.get("findings", []):
        # source_paths 只指源码；历史 QA 产物应由执行记录字段引用，不能作为本轮源码来源。
        owner["source_paths"] = [path for path in owner.get("source_paths", [])
                                 if not path.startswith("QA/results/")]
        for path in owner["source_paths"]:
            snapshot(args.root, args.evidence_dir, path)
    evidence_root = args.evidence_dir.resolve()
    dossier_refs = []
    for dossier_path in args.dossier:
        resolved = dossier_path.resolve()
        require(resolved.is_relative_to(evidence_root),
                f"专项 dossier 必须位于 evidence 目录内: {resolved}")
        dossier_refs.append(resolved.relative_to(evidence_root).as_posix())
    data["agent_audit"] = {
        "protocol": "multi-agent-v2",
        "inventory_count": len(data["features"]),
        "deep_review_count": deep,
        "deep_review_complete": complete,
        "dossiers": dossier_refs,
    }
    normalize_level_audit(data, args.evidence_dir)
    queue = completion(data, args.root, args.evidence_dir)
    queue_path = args.output.with_name(args.output.stem + "-continuation.json")
    queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n")
    data["agent_audit"]["continuation_queue"] = str(queue_path)
    data["agent_audit"]["ready_for_final"] = queue["ready_for_final"]
    data["agent_audit"]["deep_review_complete"] = queue["summary"]["complete_review"]
    if queue["ready_for_final"]:
        has_findings = bool(data.get("findings")) or bool(data.get("level_audit", {}).get("risks"))
        data["presentation"]["overall"] = "检查完成且发现问题" if has_findings else "检查完成且范围内未见问题"
        data["presentation"]["conclusion"] = (
            f"静态范围检查完成：{complete}/{len(data['features'])} 个功能已闭合，"
            f"已确认 {queue['summary']['confirmed_bug_count']} 个问题；风险单独列出。"
        )
        from render_report import validate
        validate(data, args.evidence_dir)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({**data["agent_audit"], "execution": queue["summary"]}, ensure_ascii=False))
    return 0 if queue["ready_for_final"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
