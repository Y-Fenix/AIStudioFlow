#!/usr/bin/env python3
"""Build the agent's continuation queue; an unfinished audit exits with code 2.

This is an execution gate, not a bug detector. The renderer remains responsible
for validating the report schema, branch links and evidence artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from audit_scope import manifest, target_gaps, validate_scope

DIMENSIONS = [
    "入口与正常链路", "边界与异常", "重复与异步", "状态与持久化",
    "配置变化", "升级与重装", "跨模块影响",
]
DONE = {"未见问题", "发现问题", "不适用"}
CONFIRMED = {"静态缺陷已证", "方法问题已证", "产品问题已证"}
AGENTS = {"玩法": "玩法", "关卡": "关卡", "系统": "系统", "配置": "配置与存档", "埋点": "埋点"}


def source_paths(owner: dict) -> set[str]:
    audit = owner.get("static_audit", {})
    entries = list(audit.get("cases", []))
    depth = audit.get("depth", {})
    entries += depth.get("branches", []) + depth.get("coverage", [])
    paths = set(owner.get("source_paths", []))
    for entry in entries:
        for trace in entry.get("trace", entry.get("evidence", [])):
            if trace.get("path"):
                paths.add(trace["path"])
    return paths


def completion(data: dict, root: Path, evidence_dir: Path) -> dict:
    tasks = []
    scope = validate_scope(data, root, evidence_dir)
    fixed = {f["id"]: f for f in manifest()["features"]} if scope["mode"] == "full" else {}
    if not scope["ok"]:
        tasks.append({"id": "scope:inventory", "agent": "总控", "kind": "inventory",
                      "reasons": scope["errors"],
                      "action": "从固定清单恢复完整功能范围，核对当前代码入口；禁止根据已有 dossier 缩减清单。"})
    missing = partial = complete = drift = external = 0
    hash_cache = {}

    def changed(path):
        if path not in hash_cache:
            live = root / path
            saved = evidence_dir / "sources" / (path + ".txt")
            hash_cache[path] = (
                not live.is_file() or not saved.is_file()
                or hashlib.sha256(live.read_bytes()).digest()
                != hashlib.sha256(saved.read_bytes()).digest()
            )
        return hash_cache[path]

    for kind, owners in [("feature", data.get("features", [])),
                         ("configuration", data.get("configuration_groups", []))]:
        for owner in owners:
            audit = owner.get("static_audit", {})
            depth = audit.get("depth", {})
            cases = audit.get("cases", [])
            reasons = []
            dimensions = []
            has_dossier = bool(depth.get("branches")) if kind == "feature" else bool(cases)
            if not has_dossier:
                reasons.append("只有功能盘点，缺专项分支审查；沿入口追到消费者并生成 dossier。")
                if kind == "feature":
                    missing += 1
                    dimensions = list(DIMENSIONS)
            else:
                if kind == "feature" and owner.get("id") in fixed:
                    reasons.extend(target_gaps(owner, fixed[owner["id"]]))
                for row in depth.get("coverage", []):
                    if row.get("status") not in {"已闭合", "不适用"}:
                        dimensions.append(row.get("dimension", ""))
                        reasons.append(str(row.get("gap") or "补齐该维度的真实分支和场景。"))
                for case in cases:
                    if case.get("verdict") not in DONE:
                        dimensions.append(case.get("dimension", ""))
                        reasons.append(str(case.get("reason") or case.get("scenario") or "补齐本地场景结论。"))
                if audit.get("status") != "已完成":
                    reasons.append("专项静态审查尚未闭合。")
                # A free-form gap must not disappear merely because cases are green.
                reasons.extend(str(x) for x in owner.get("gaps", []))
                if not cases:
                    reasons.append("缺少逐场景检查记录。")
            changed_sources = [p for p in sorted(source_paths(owner)) if changed(p)] if has_dossier else []
            if owner.get("source_drift") or changed_sources:
                reasons.append("证据与当前源码尚未复核；只续查变化的路径及其消费者。")
                if kind == "feature":
                    drift += 1
            external += len(owner.get("external_checks", []))
            if reasons:
                if kind == "feature" and has_dossier:
                    partial += 1
                category = owner.get("display", {}).get("category", "配置" if kind == "configuration" else "系统")
                tasks.append({
                    "id": f"{kind}:{owner['id']}", "owner_id": owner["id"],
                    "name": owner.get("display", {}).get("name", owner.get("name", owner["id"])),
                    "agent": AGENTS.get(category, category), "kind": kind,
                    "dimensions": list(dict.fromkeys(d for d in dimensions if d)),
                    "reasons": list(dict.fromkeys(reasons)),
                    "source_paths": sorted(source_paths(owner)),
                    "changed_sources": changed_sources,
                    "action": "由 Agent 续查源码，必要时执行隔离本地探针；不要转成人工验收。",
                })
            elif kind == "feature":
                complete += 1

    level = data.get("level_audit", {})
    for stage in ("layout", "solvability", "visual"):
        row = level.get(stage, {})
        if (level.get("pipeline_version") != 2
                or row.get("status") not in {"检查完成未见问题", "发现问题"}
                or not row.get("total") or row.get("checked") != row.get("total")):
            tasks.append({
                "id": f"level:{stage}", "owner_id": stage, "agent": "关卡", "kind": "level",
                "reasons": [row.get("summary") or "缺当前基线逐关结果。"],
                "action": "自动补跑对应阶段并保存结果；求解预算未定不是无解，不转交人工通关。",
            })
    if not data.get("features"):
        tasks.append({"id": "inventory", "agent": "总控", "kind": "inventory",
                      "action": "从真实入口建立功能清单，空清单不能算全量完成。"})

    # Batches are scheduling inputs for the host agent, not subprocess commands.
    batches = []
    for agent in dict.fromkeys(t["agent"] for t in tasks):
        owned = [t["id"] for t in tasks if t["agent"] == agent]
        for index in range(0, len(owned), 3):
            batches.append({"agent": agent, "task_ids": owned[index:index + 3]})
    return {
        "schema_version": 1, "ready_for_final": not tasks,
        "scope": scope,
        "summary": {"feature_count": len(data.get("features", [])),
                    "missing_dossier": missing, "partial_review": partial,
                    "complete_review": complete, "source_recheck": drift,
                    "external_facts_out_of_scope": external,
                    "confirmed_bug_count": len({f["id"] for f in data.get("findings", [])
                                                if f.get("kind") in CONFIRMED}),
                    "pending_tasks": len(tasks)},
        "tasks": tasks, "batches": batches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.data.read_text())
    result = completion(data, args.root, args.evidence_dir)
    # Completion alone does not prove that the dossier/evidence schema is valid.
    if result["ready_for_final"]:
        from render_report import validate
        try:
            validate(data, args.evidence_dir)
        except (ValueError, KeyError, TypeError) as exc:
            result["ready_for_final"] = False
            result["validation_error"] = str(exc)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"ready_for_final": result["ready_for_final"], **result["summary"]}, ensure_ascii=False))
    return 0 if result["ready_for_final"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
