"""Resumable, read-only release pipeline for the testing department.

The orchestrator deliberately stops at evidence collection.  Device actions,
real platform delivery and external issue publication remain explicit gates.
"""
from __future__ import annotations

import json
import os
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .QA_release_contract import QA_verify_profile
from .QA_release_runner import QA_run_release_checks

QA_SCHEMA_VERSION = 1
QA_RUNTIME_RISKS = (
    ("runtime_payment", "Blocker", "真实内购拉起、支付、验单和到账未执行"),
    ("runtime_tracking", "High", "数数、Adjust、Firebase、BI 平台入库未执行"),
    ("runtime_ads", "High", "插屏/激励连续播放及奖励下发未执行"),
    ("runtime_installation", "High", "覆盖安装、卸载重装和身份迁移未执行"),
)


def QA_now():
    return datetime.now(timezone.utc).isoformat()


def QA_write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".qa-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def QA_risk_rows():
    return [{"id": key, "severity": severity, "status": "unverified", "reason": reason}
            for key, severity, reason in QA_RUNTIME_RISKS]


def QA_project_static(profile, artifact_dir: Path):
    """Collect safe local evidence without Git, builds, network or writes."""
    artifact_dir.mkdir(parents=True, exist_ok=True)
    repositories = {}
    for name, item in sorted(profile["repositories"].items()):
        root = Path(item["root"])
        repositories[name] = {
            "root": str(root),
            "available": root.is_dir(),
            "file_count": sum(1 for p in root.rglob("*") if p.is_file()) if root.is_dir() else 0,
        }
    skills = {name: {"root": item["root"], "sha256": item["sha256"]}
              for name, item in sorted(profile["skills"].items())}
    evidence = {
        "schema_version": 1,
        "status": "partial",
        "reason": "仅完成路径、Skill 冻结和本地只读盘点；专项运行时链路未执行",
        "repositories": repositories,
        "skills": skills,
        "cross_repo_snapshot": "not_executed",
        "git": "not_used",
    }
    QA_write_json(artifact_dir / "project-static.json", evidence)
    return {"status": "completed", "evidence": "project-static.json",
            "scope": "partial", "findings": [], "attempts": 1}


def QA_initial_state(profile, run_id):
    return {
        "schema_version": QA_SCHEMA_VERSION,
        "run_id": run_id,
        "profile_sha256": profile["sha256"],
        "created_at": QA_now(),
        "updated_at": QA_now(),
        "phases": {
            "sdk_static": {"status": "pending", "attempts": 0},
            "project_static": {"status": "pending", "attempts": 0},
        },
    }


def QA_run_release_pipeline(profile, report_dir, *, resume=False):
    """Run or resume the local release pipeline and return the report."""
    verification = QA_verify_profile(profile)
    if not verification["valid"]:
        raise ValueError("profile is stale or invalid: " + ", ".join(verification["gaps"]))
    report_dir = Path(report_dir).expanduser().resolve()
    state_path, report_path = report_dir / "state.json", report_dir / "report.json"
    if report_dir.exists() and not resume:
        raise ValueError("report directory already exists; use resume=True")
    report_dir.mkdir(parents=True, exist_ok=True)
    if resume:
        if not state_path.is_file() or not report_path.is_file():
            raise ValueError("resume requires state.json and report.json")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("profile_sha256") != profile["sha256"]:
            raise ValueError("profile changed; refusing to resume")
    else:
        state = QA_initial_state(profile, secrets.token_hex(12))
        QA_write_json(state_path, state)

    def QA_save_state():
        state["updated_at"] = QA_now()
        QA_write_json(state_path, state)

    sdk = state["phases"]["sdk_static"]
    if sdk["status"] != "completed":
        sdk["attempts"] += 1
        QA_save_state()
        try:
            sdk_dir = report_dir / ("sdk-static" if sdk["attempts"] == 1
                                    else "sdk-static-retry-" + str(sdk["attempts"]))
            result = QA_run_release_checks(profile, sdk_dir)
            sdk.update({"status": "completed", "result": result,
                        "artifact": str(sdk_dir.relative_to(report_dir) / "result.json")})
        except Exception as error:
            sdk.update({"status": "failed", "error": type(error).__name__ + ": " + str(error)})
            QA_save_state()
            raise
        QA_save_state()

    project = state["phases"]["project_static"]
    if project["status"] != "completed":
        project["attempts"] += 1
        QA_save_state()
        try:
            result = QA_project_static(profile, report_dir / "project-static")
            project.update(result)
        except Exception as error:
            project.update({"status": "failed", "error": type(error).__name__ + ": " + str(error)})
            QA_save_state()
            raise
        QA_save_state()

    report = {
        "schema_version": QA_SCHEMA_VERSION,
        "run_id": state["run_id"],
        "status": "completed_with_findings",
        "release_verified": False,
        "profile_sha256": profile["sha256"],
        "phases": state["phases"],
        "risks": QA_risk_rows(),
        "findings": [],
        "manual_authorization": {
            "external_issue_creation": "not_authorized",
            "real_device_actions": "not_authorized",
            "real_payment": "not_authorized",
        },
        "generated_at": QA_now(),
    }
    QA_write_json(report_path, report)
    return report

