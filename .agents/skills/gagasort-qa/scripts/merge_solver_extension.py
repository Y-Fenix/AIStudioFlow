#!/usr/bin/env python3
"""Merge an actual extended solver run without overwriting layout/3D evidence."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def solved(row):
    return (row.get("validation", {}).get("valid") is True and row["status"] == "Solvable"
            and row.get("replay", {}).get("has_completed") is True
            and row.get("replay", {}).get("independent_runtime") is True)


def verify_manifest(levels, extended, manifest_path):
    manifest = read(manifest_path)
    baseline = read(levels.parent / "baseline.json")
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    if (manifest["head"] != baseline["head"] or manifest["head_after"] != baseline["head"]
            or manifest["exit_code"] != 0 or manifest["sources_changed"]
            or manifest["input_sha256"] != sha(levels / "solver-input.json")
            or manifest["output_sha256"] != sha(extended)):
        raise ValueError("扩展求解不是本轮相同输入的成功执行，不能合并")
    root = Path(baseline["root"])
    current = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if current != baseline["head"] or Path(manifest["repo"]).resolve() != root.resolve():
        raise ValueError("扩展求解仓库或 HEAD 不匹配")
    for item in manifest["sources"] + manifest.get("adaptations", []):
        path = Path(item.get("path", item.get("source", "")))
        if not path.is_file() or sha(path) != item["sha256"]:
            raise ValueError("扩展求解源码已变化：" + str(path))


def merge(levels, extended, run_id, manifest_path):
    verify_manifest(levels, extended, manifest_path)
    initial_path = levels / "solver-kernel.json"
    first, extra = read(initial_path), read(extended)
    inventory = read(levels / "level-inventory.json")
    ids = {row["level_id"] for row in inventory["levels"]}

    def index(rows):
        indexed = {row["level_id"]: row for row in rows}
        if len(indexed) != len(rows) or set(indexed) != ids:
            raise ValueError("求解结果 ID 必须与本轮清单完全一致，不能固定历史关数")
        return indexed

    a, b = index(first["levels"]), index(extra["levels"])
    result = read(levels / "solvability-results.json")
    fragment = read(levels / "report-fragment.json")
    table = index(fragment["table"])
    selected = []
    for old in result["results"]:
        key = old["level_id"]
        detail_path = levels.parent / old["evidence"][0]
        detail = read(detail_path)
        # A proved replay or definite invalid/unsolvable result cannot be weakened by a timeout.
        prior = detail.get("solver", a[key])
        definite = lambda row: solved(row) or row.get("validation", {}).get("valid") is False or row["status"] in {"Invalid", "Unsolvable"}
        source = prior if definite(prior) else a[key] if definite(a[key]) else b[key]
        keep = source is not b[key]
        ok = solved(source)
        verdict = ("未见问题" if ok else "发现问题" if source.get("validation", {}).get("valid") is False
                   or source["status"] in {"Invalid", "Unsolvable"} else "未定")
        row = deepcopy(old)
        budget = detail.get("solver_budget", first.get("budget")) if source is prior else (first if keep else extra).get("budget")
        row.update(verdict=verdict, status=source["status"], replay_completed=ok, budget=budget,
                   checks=[dict(name="正式无道具求解与全新运行时回放", verdict=verdict,
                                status=source["status"], reason=source.get("reason", ""))])
        selected.append(row)
        attempts = detail.get("solver_attempts", [dict(source=initial_path.relative_to(levels.parent).as_posix(), status=a[key]["status"], budget=first.get("budget"))])
        attempt = dict(source=extended.relative_to(levels.parent).as_posix(), status=b[key]["status"], budget=extra.get("budget"))
        if attempt not in attempts:
            attempts.append(attempt)
        detail.update(solver=source, solver_budget=budget,
                      solver_attempts=attempts)
        save(detail_path, detail)
        table[key]["solvability"] = ("已回放通关" if ok else "关卡输入不合法" if source.get("validation", {}).get("valid") is False
                                    or source["status"] == "Invalid" else "已确认无解" if source["status"] == "Unsolvable" else "预算内未定")
    if {row["level_id"] for row in selected} != ids or len(selected) != len(ids):
        raise ValueError("原始逐关结果缺漏或重复")
    count = sum(row["replay_completed"] for row in selected)
    unknown = sum(row["verdict"] == "未定" for row in selected)
    bad = sum(row["verdict"] == "发现问题" for row in selected)
    summary = f"{len(ids)} 关全量执行并扩展预算补跑；{count} 关找到无道具解且独立回放通关，{unknown} 关预算内未定，{bad} 关确认无解或输入不合法。未定不等于无解。"
    result.update(results=selected, checked=len(ids) - unknown, attempted=len(ids))
    save(levels / "solvability-results.json", result)
    stage = fragment["solvability"]
    stage.update(status="检查未完成" if unknown else "发现问题" if bad else "检查完成未见问题",
                 checked=result["checked"], summary=summary)
    stage["run_ids"] = list(dict.fromkeys(stage.get("run_ids", []) + [run_id]))
    stage["evidence"] = list(dict.fromkeys(stage.get("evidence", []) + [extended.relative_to(levels.parent).as_posix()]))
    for row in fragment["summary_rows"]:
        if row["id"] == "solver":
            row.update(status=stage["status"], summary=summary)
    save(levels / "report-fragment.json", fragment)
    return dict(success=count, unknown=unknown, problems=bad, total=len(ids), summary=summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--levels-dir", type=Path, required=True)
    parser.add_argument("--extended", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--manifest", type=Path, required=True, help="本次扩展编译/执行生成的 manifest.json")
    args = parser.parse_args()
    print(json.dumps(merge(args.levels_dir.resolve(), args.extended.resolve(), args.run_id, args.manifest.resolve()), ensure_ascii=False))


if __name__ == "__main__":
    main()
