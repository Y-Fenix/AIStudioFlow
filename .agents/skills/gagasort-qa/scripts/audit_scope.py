#!/usr/bin/env python3
"""Lock the maintained full-project scope before review; never infer it from dossiers."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess

SKILL = Path(__file__).resolve().parents[1]
MANIFEST = SKILL / "assets/audit-scope.json"
CATEGORIES = ("玩法", "关卡", "系统", "配置", "埋点")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(value):
    p = PurePosixPath(value)
    if not value or p.is_absolute() or ".." in p.parts or "\\" in value:
        raise ValueError("范围路径必须在仓库内：" + value)
    return value


def manifest(path=MANIFEST):
    obj = read(path)
    ids = [f["id"] for f in obj["features"]]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("固定清单为空或有重复功能编号")
    for f in obj["features"]:
        if f["category"] not in CATEGORIES or not f["check_targets"] or not f["sources"] or not f["required_sources"]:
            raise ValueError("固定功能缺分类、检查内容或源码锚点：" + f["id"])
        for pattern in f["sources"] + f["required_sources"]:
            relative(pattern)
    for pattern in obj["watch_roots"] + obj.get("watch_files", []):
        relative(pattern)
    for row in obj.get("exclusions", []):
        relative(row["pattern"])
        if not row.get("reason"):
            raise ValueError("排除项必须有理由")
    return obj


def snapshot(root, run_id, manifest_path=MANIFEST):
    root = root.resolve()
    obj = manifest(manifest_path)
    errors, files, excluded, owners = [], set(), {}, {}
    for name in obj["watch_roots"]:
        base = root / name
        if not base.is_dir():
            errors.append("源码扫描根目录缺失：" + name)
        else:
            files.update(p.relative_to(root).as_posix() for p in base.rglob("*.cs") if p.is_file())
    def expand(pattern):
        return {p.relative_to(root).as_posix() for p in root.glob(pattern) if p.is_file()}
    for row in obj.get("exclusions", []):
        for name in expand(row["pattern"]) & files:
            excluded[name] = row["reason"]
    inventory = []
    for f in obj["features"]:
        paths = set().union(*(expand(pattern) for pattern in f["sources"])) - set(excluded)
        for pattern in f["required_sources"]:
            if not (expand(pattern) - set(excluded)):
                errors.append(f["id"] + " 必备源码入口缺失：" + pattern)
        if not paths:
            errors.append(f["id"] + " 没有可盘点的源码")
        for name in paths:
            owners.setdefault(name, []).append(f["id"])
        inventory.append({**f, "source_paths": sorted(paths)})
    unassigned = sorted(files - set(owners) - set(excluded))
    if unassigned:
        errors.append("存在未归属功能的源码，须先补清单：" + str(len(unassigned)) + " 个")
    watched = set(files)
    for name in obj.get("watch_files", []):
        if not (root / name).is_file():
            errors.append("模块索引缺失：" + name)
        else:
            watched.add(name)
    # Include sources outside the scan roots explicitly referenced by the manifest.
    watched.update(owners)
    for name in watched:
        if not (root / name).resolve().is_relative_to(root):
            raise ValueError("范围源码软链接越界：" + name)
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True).rstrip("\n")
    if git("rev-parse", "--show-toplevel") != str(root):
        raise ValueError("--root 必须是被测游戏仓库根目录")
    return {
        "schema_version": 1, "scope_version": obj["scope_version"],
        "manifest_sha256": sha(manifest_path),
        "baseline": {"root": str(root), "run_id": run_id, "head": git("rev-parse", "HEAD"),
                     "branch": git("branch", "--show-current"), "submodules": git("submodule", "status")},
        "expected_count": len(inventory),
        "category_counts": dict(Counter(f["category"] for f in inventory)),
        "inventory": inventory, "source_hashes": {p: sha(root / p) for p in sorted(watched)},
        "unassigned_sources": unassigned, "excluded_sources": excluded, "errors": errors,
    }


def targeted_scope(data):
    control = data.get("scope_control", {})
    features = data.get("features", [])
    ids = [f.get("id") for f in features]
    errors = []
    if not control.get("reason") or not ids or len(ids) != len(set(ids)) or set(ids) != set(control.get("feature_ids", [])):
        errors.append("定向模式须记录用户指定范围的原因和完整 feature_ids，不能默认绕过全量清单")
    return {"mode": "targeted", "ok": not errors, "expected_count": len(ids), "errors": errors}


def validate_scope(data, root, evidence, *, require_full=False, manifest_path=MANIFEST):
    mode = data.get("scope_control", {}).get("mode", "full")
    if mode == "targeted" and not require_full:
        return targeted_scope(data)
    result = {"mode": "full", "ok": False, "expected_count": 0, "errors": []}
    errors = result["errors"]
    if mode != "full":
        errors.append("全量交付入口不接受定向范围")
    obj = manifest(manifest_path)
    expected = {f["id"]: f for f in obj["features"]}
    result["expected_count"] = len(expected)
    actual = [f.get("id", "") for f in data.get("features", [])]
    result["missing_ids"] = sorted(set(expected) - set(actual))
    result["unexpected_ids"] = sorted(set(actual) - set(expected))
    result["duplicate_ids"] = sorted(k for k, n in Counter(actual).items() if n > 1)
    for key in ("missing_ids", "unexpected_ids", "duplicate_ids"):
        if result[key]:
            errors.append(key + "：" + ", ".join(result[key]))
    for f in data.get("features", []):
        fixed = expected.get(f.get("id"))
        if fixed and any(f.get("display", {}).get(k) != fixed[k] for k in ("category", "group", "name")):
            errors.append(f["id"] + " 的分类/业务名与固定清单不符")
    if root is None or evidence is None or not (evidence / "scope-lock.json").is_file():
        errors.append("缺本轮 scope-lock.json；须在分发专项前锁定完整范围")
    else:
        try:
            lock = read(evidence / "scope-lock.json")
            current = snapshot(root, data.get("baseline", {}).get("run_id", ""), manifest_path)
            errors.extend(current["errors"])
            if lock != current:
                errors.append("范围锁与当前源码、清单或运行基线不一致；先盘点变化并重新锁定新批次，不能改旧锁冒充已审")
            baseline = data.get("baseline", {})
            for key in ("root", "head", "branch", "run_id"):
                if baseline.get(key) != current["baseline"][key]:
                    errors.append("报告范围基线不一致：" + key)
            result["scope_version"] = current["scope_version"]
            result["category_counts"] = current["category_counts"]
        except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
            errors.append("范围锁无法复核：" + str(exc))
    result["ok"] = not errors
    return result


def seed(lock):
    return [{"id": f["id"], "name": f["name"], "inventory_sources": f["source_paths"], "source_paths": [],
             "checks": f["check_targets"], "related_findings": [],
             "display": {**{k: f[k] for k in ("category", "group", "name")},
                         "check_summary": "；".join(f["check_targets"])},
             "installation": {}, "assessment": {}, "gaps": [],
             "static_audit": {"status": "未完成", "summary": "范围已锁定，尚未执行审查。", "cases": []}}
            for f in lock["inventory"]]


def target_gaps(owner, fixed):
    """A fixed sub-check only closes through a finished, source-backed scenario."""
    covered = set()
    for case in owner.get("static_audit", {}).get("cases", []):
        if case.get("verdict") in {"未见问题", "发现问题", "不适用"} and case.get("trace"):
            covered.update(case.get("scope_targets", []))
    return ["固定检查内容未闭合：" + target for target in fixed["check_targets"] if target not in covered]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "check"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--data", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        if not args.run_id:
            parser.error("prepare 必须指定 --run-id")
        paths = [args.evidence_dir / name for name in ("scope-lock.json", "feature-inventory.json")]
        if any(p.exists() for p in paths):
            parser.error("本轮范围已存在，禁止覆盖；源码/清单变化须创建新批次")
        lock = snapshot(args.root, args.run_id)
        save(paths[0], lock)
        save(paths[1], {"scope_control": {"mode": "full"}, "baseline": lock["baseline"], "features": seed(lock)})
        result = {k: lock[k] for k in ("scope_version", "expected_count", "category_counts", "unassigned_sources", "errors")}
        result["ok"] = not lock["errors"]
    else:
        if not args.data:
            parser.error("check 必须指定 --data")
        result = validate_scope(read(args.data), args.root.resolve(), args.evidence_dir, require_full=True)
        save(args.evidence_dir / "scope-check.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
