#!/usr/bin/env python3
"""Merge the local GagaSort tracking audit into the fixed v2.1 report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def snapshot(root: Path, evidence: Path, path: str) -> None:
    source = root / path
    if not source.is_file():
        return
    target = evidence / "sources" / (path + ".txt")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())


def collect_paths(obj: dict) -> set[str]:
    paths: set[str] = set()
    for feature in obj.get("features", []):
        paths.update(feature.get("source_paths", []))
        for case in feature.get("static_audit", {}).get("cases", []):
            paths.update(x.get("path", "") for x in case.get("trace", []))
        for case in feature.get("checks", []):
            paths.update(x.get("path", "") for x in case.get("trace", []))
    for finding in obj.get("findings", []):
        paths.update(finding.get("source_paths", []))
        paths.update(x.get("path", "") for x in finding.get("static_proof", {}).get("trace", []))
    for item in obj.get("code_only_events", []):
        paths.update(x.get("path", "") for call in item.get("calls", []) for x in [call])
    return {x for x in paths if x}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-data", type=Path, required=True)
    ap.add_argument("--dossier", type=Path, required=True)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--evidence-dir", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    data = json.loads(args.base_data.read_text())
    dossier = json.loads(args.dossier.read_text())
    existing_features = {x["id"] for x in data.get("features", [])}
    existing_findings = {x["id"] for x in data.get("findings", [])}
    new_features = [x for x in dossier.get("features", []) if x["id"] not in existing_features]
    new_findings = [x for x in dossier.get("findings", []) if x["id"] not in existing_findings]
    for feature in new_features:
        case_ids = {case.get("id") for case in feature.get("static_audit", {}).get("cases", [])}
        for item in feature.get("external_checks", []):
            item["local_case_ids"] = [
                "tracking-event-json-serialization"
                if case_id == "tracking-event-serialization"
                and "tracking-event-json-serialization" in case_ids
                else case_id
                for case_id in item.get("local_case_ids", [])
            ]
        for case in feature.get("static_audit", {}).get("cases", []):
            if case.get("verdict") == "风险待确认":
                case["verdict"] = "待核实"
                case.setdefault("reason", "专项审查识别到风险，但本轮证据不足以确认缺陷或排除问题。")
    for finding in new_findings:
        finding.setdefault(
            "missing",
            "本轮只核客户端事件构造代码；真实平台 SDK 接收及服务端入库未验证。",
        )
        proof = finding.get("static_proof", {})
        finding.setdefault(
            "display",
            {
                "category": "埋点",
                "title": finding.get("title", finding.get("id", "埋点问题")),
                "condition": finding.get("condition", "专项静态审查覆盖的代码路径"),
                "cause": finding.get("cause", "详见源码静态证据。"),
                "impact": finding.get("impact", "详见问题影响分析。"),
                "expected": finding.get("expected", "详见埋点合同。"),
                "actual": finding.get("actual", "详见源码静态证据。"),
                "whitebox_steps": proof.get("steps", []),
            },
        )
    data.setdefault("features", []).extend(new_features)
    data.setdefault("findings", []).extend(new_findings)
    paths = collect_paths(dossier)
    for path in paths:
        snapshot(args.root, args.evidence_dir, path)
    tracking_events = dossier.get("scan_summary", {}).get("table_events", dossier.get("contract", {}).get("event_count", 0))
    scan_summary = dossier.get("scan_summary", {})
    tracking_code_events = scan_summary.get(
        "code_events", scan_summary.get("scanner_candidate", {}).get("code_events", 0)
    )
    tracking_findings = len(new_findings)
    data["presentation"]["overall"] = "执行不完整" if any(x.get("static_audit", {}).get("status") != "已完成" for x in new_features) else data["presentation"].get("overall", "执行不完整")
    data["presentation"]["conclusion"] += f" 埋点专项已固化 {tracking_events} 个表内事件，扫描到 {tracking_code_events} 个代码事件，新增 {len(new_features)} 条埋点功能记录和 {tracking_findings} 个静态问题；表外事件保留棕色待确认。"
    data["presentation"]["execution_scope"] += " 已读取本地固化 GagaSort 埋点表，完成事件双向覆盖、统一出口、属性字段和升级重装影响静态审查。"
    data["presentation"]["supplement_summary"] += " 埋点表内漏报/属性矛盾按静态问题展示；代码存在但表外的事件只记为契约待确认；真实 SDK 入库仍属外部事实。"
    audit = data.setdefault("agent_audit", {})
    audit["tracking_contract_events"] = tracking_events
    audit["tracking_code_events"] = tracking_code_events
    audit["tracking_feature_count"] = len(new_features)
    audit["tracking_finding_count"] = tracking_findings
    audit.setdefault("dossiers", []).append(str(args.dossier))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"features_added": len(new_features), "findings_added": tracking_findings, "paths_snapshotted": len(paths)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
