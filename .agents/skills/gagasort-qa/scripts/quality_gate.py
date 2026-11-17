#!/usr/bin/env python3
"""Build the immutable quality snapshot for one audit batch.

This module only accounts for the current report data and continuation queue.
It never imports findings from an older report and it never turns a partial
review into a full-project conclusion.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from audit_scope import validate_scope


SCHEMA_VERSION = 1


def _stable_ids(items, kind):
    return sorted({str(item.get("id", "")) for item in items if item.get("id")}, key=lambda value: (value.casefold(), value))


def _level_counts(data):
    level = data.get("level_audit", {})
    inventory = level.get("inventory_count")
    if inventory is None:
        table = level.get("table") or []
        inventory = len(table)
    checked = 0
    total = 0
    for key in ("layout", "solvability", "visual"):
        row = level.get(key, {})
        total = max(total, int(row.get("total") or 0))
        checked = max(checked, int(row.get("checked") or 0))
    return int(inventory or 0), int(checked), int(total or inventory or 0)


def _report_core_hash(data):
    """Hash the current report data without the snapshot's self-referential field."""
    core = dict(data)
    core.pop("quality_gate", None)
    return hashlib.sha256(
        json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_quality_gate(data, queue, evidence_dir: Path | None = None):
    """Return deterministic counts and completion semantics for this batch."""
    profile = {}
    if evidence_dir:
        profile_path = Path(__file__).resolve().parents[1] / "assets" / "delivery-profile.json"
        if profile_path.is_file():
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
    features = data.get("features", [])
    dossiers = data.get("agent_audit", {}).get("dossiers", [])
    findings = data.get("findings", [])
    confirmed = {str(f["id"]) for f in findings
                 if f.get("id") and f.get("kind") in {"静态缺陷已证", "方法问题已证", "产品问题已证"}}
    inventory_count = len(features)
    deep_review_count = sum(bool(f.get("static_audit", {}).get("depth", {}).get("branches")) for f in features)
    incomplete_ids = {t.get("owner_id") for t in queue.get("tasks", []) if t.get("kind") == "feature"}
    deep_review_complete = sum(f.get("static_audit", {}).get("status") == "已完成"
                               and bool(f.get("static_audit", {}).get("depth", {}).get("branches"))
                               and f.get("id") not in incomplete_ids for f in features)
    level_inventory_count, level_checked_count, level_total_count = _level_counts(data)
    pending = list(queue.get("tasks", []))
    root = data.get("baseline", {}).get("root")
    scope = validate_scope(data, Path(root) if root else None, evidence_dir)
    audit_complete = bool(queue.get("ready_for_final")) and scope["ok"] and deep_review_complete == inventory_count and inventory_count > 0
    quality_status = "通过" if audit_complete else "部分完成"
    report_data_hash = _report_core_hash(data)
    return {
        "schema_version": SCHEMA_VERSION,
        "workflow_version": profile.get("workflow_version"),
        "report_contract_version": data.get("report_contract_version"),
        "baseline": {
            "run_id": data.get("baseline", {}).get("run_id"),
            "head": data.get("baseline", {}).get("head"),
            "branch": data.get("baseline", {}).get("branch"),
        },
        "inventory_count": inventory_count,
        "scope": scope,
        "dossier_count": len(_stable_ids([{"id": d} for d in dossiers], "dossier")),
        "deep_review_count": deep_review_count,
        "deep_review_complete": deep_review_complete,
        "complete_review": scope["ok"] and deep_review_complete == inventory_count and inventory_count > 0,
        "incomplete_count": len(pending),
        "confirmed_finding_count": len(confirmed),
        "confirmed_finding_ids": sorted(confirmed, key=lambda value: (value.casefold(), value)),
        "risk_count": len([f for f in findings if f.get("id") and f.get("id") not in confirmed]),
        "level_inventory_count": level_inventory_count,
        "level_checked_count": level_checked_count,
        "level_total_count": level_total_count,
        "execution_record_count": len(data.get("suites", [])) + len(data.get("additional_runs", [])),
        "execution_finished_count": sum(r.get("status", "").startswith("未执行") is False
                                         and r.get("exit_code") == 0
                                         for r in data.get("suites", []) + data.get("additional_runs", [])),
        "pending_task_count": len(pending),
        "audit_complete": audit_complete,
        "report_ready": False,
        "quality_status": quality_status,
        "report_data_sha256": report_data_hash,
    }
