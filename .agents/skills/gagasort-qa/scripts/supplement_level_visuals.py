#!/usr/bin/env python3
"""Supplement non-flat levels with identical production mesh triangles, outside Unity.

Only closes the former non-flat gap when all exported sources match the initial
hashes and every 3D check is clear. Other gaps and positive hits remain explicit.
"""
import argparse
import difflib
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess

from level_3d_checks import analyze, smoke


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_checks(source, settings):
    samples = source["samples"]
    arc = [0]
    for a, b in zip(samples, samples[1:]):
        arc.append(arc[-1] + math.dist(a, b))
    threshold = (settings["WaterChannelWidth"] + 2 * settings["WallWidth"]) * 2
    wall = analyze(source["raw_shell"], "wall", source["sample_rows"], arc, threshold)
    water = analyze(source["raw_water"], "water", source["sample_rows"], arc, threshold)
    risk = wall["nonlocal_intersections"] + water["nonlocal_intersections"] + (water["winding_negative_z"] or 0)
    contacts = wall["counts"]["boundary_or_tolerance_contact"] + water["counts"]["boundary_or_tolerance_contact"]
    return dict(kind=source["kind"], source=source["source"], mesh_hashes=source["mesh_hashes"],
                wall=wall, water=water, clear=not risk and not contacts,
                limitations=["只检查墙顶与水面中央带的高度三角形，不代表 GPU 实际画面。",
                             "面积/高度容差为 1e-5；近接、侧面、阴影、材质、相机和遮挡不冒充已验收。"])


def merge_clear(levels_dir, supplement):
    visual = read(levels_dir / "visual-summary.json")
    fragment = read(levels_dir / "report-fragment.json")
    by_id = {row["level_id"]: row for row in supplement["levels"]}
    closed = []
    for row in visual["results"]:
        proof = by_id.get(row["level_id"])
        if not proof:
            continue
        # Close exactly this old detector gap; never hide other missing checks or a hit.
        errors = row.get("errors", [])
        only_nonflat = bool(errors) and all("非平面动态路径" in error for error in errors)
        if (row["verdict"] != "未定" or not only_nonflat or not proof.get("sources")
                or not all(s["clear"] for s in proof["sources"])):
            continue
        if row.get("wall_risk") or row.get("water_risk"):
            continue
        row["original_verdict"] = row["verdict"]
        row["original_errors"] = errors
        row.update(verdict="未见问题", errors=[], supplement_3d=proof)
        detail_path = levels_dir.parent / row["evidence"][0]
        detail = read(detail_path)
        detail["visual"]["supplement_3d"] = proof
        save(detail_path, detail)
        closed.append(row["level_id"])
    visual["checked"] = sum(row["verdict"] != "未定" for row in visual["results"])
    result_by_id = {row["level_id"]: row for row in visual["results"]}
    for row in fragment["table"]:
        row["visual"] = result_by_id[row["level_id"]]["verdict"]
    stage = fragment["visual"]
    stage["checked"] = visual["checked"]
    stage["status"] = ("检查未完成" if visual["checked"] < visual["total"] else
                       "有风险待确认" if fragment.get("risks") else "检查完成未见问题")
    stage["summary"] += (" 非平面指定三维补证已闭合 " + str(len(closed)) + " 关；当前几何范围内 "
                         + str(visual["total"] - visual["checked"]) + " 关未定；原始结果保留，未验 GPU 画面。")
    evidence = "levels/nonflat-3d/results.json"
    if evidence not in stage["evidence"]:
        stage["evidence"].append(evidence)
    for row in fragment["summary_rows"]:
        if row["id"] in {"wall", "water"}:
            count = stage[row["id"] + "_risk_count"]
            row["status"] = "有风险待确认" if count else "检查未完成" if visual["checked"] < visual["total"] else "检查完成未见问题"
    save(levels_dir / "visual-summary.json", visual)
    save(levels_dir / "report-fragment.json", fragment)
    return closed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo", "levels-dir", "visual-build", "spline-build", "build-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    repo, levels = args.repo.resolve(), args.levels_dir.resolve()
    original_results = read(levels / "visual-results.json")
    selected = [row for row in original_results["levels"] if any(s.get("flat") is False for s in row.get("sources", []))]
    if not selected:
        print("无非平面网格，无需三维补证。")
        return
    base = args.visual_build.resolve()
    build = args.build_dir.resolve()
    build.mkdir(parents=True, exist_ok=True)
    out = levels / "nonflat-3d"
    out.mkdir(exist_ok=True)
    manifest = read(base / "manifest.json")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    if manifest["head"] != head:
        raise ValueError("原始网格不是当前 HEAD")
    for item in manifest["sources"] + manifest["kernel_assemblies"]:
        if sha(Path(item["path"])) != item["sha256"]:
            raise ValueError("原始网格依赖已变化：" + item["path"])
    source = Path(__file__).with_name("level_visual_probe.cs")
    old = source.read_text()
    marker = "mesh_hashes=new{water=MeshHash(water),shell=MeshHash(shell)},"
    if old.count(marker) != 1:
        raise ValueError("探针导出接缝已变化，不得猜测替换")
    new = old.replace(marker, marker + "raw_water=new{vertices=Verts(water.vertices),triangles=water.triangles},raw_shell=new{vertices=Verts(shell.vertices),triangles=shell.triangles},")
    export = out / "MeshExportProbe.cs"
    export.write_text(new)
    (out / "MeshExportProbe.diff").write_text("".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True))))
    inputs = read(levels / "geometry-input.json")
    ids = {row["level_id"] for row in selected}
    inputs["levels"] = [row for row in inputs["levels"] if row["level_id"] in ids]
    save(out / "input.json", inputs)
    payload = read(base / "visual-input.json")
    save(out / "visual-settings.json", payload)
    rsp = (base / "VisualProbe.rsp").read_text().replace(str(base / "VisualProbe.dll"), str(build / "VisualProbe.dll")).replace(str(source), str(export))
    (out / "build.rsp").write_text(rsp)
    for path in base.glob("*.dll"):
        if path.name != "VisualProbe.dll":
            shutil.copy2(path, build / path.name)
    shutil.copy2(base / "VisualProbe.runtimeconfig.json", build / "VisualProbe.runtimeconfig.json")
    runtime = Path(read(args.spline_build / "manifest.json")["runtime"])
    unity = runtime.parents[3]
    dotnet = unity / "NetCoreRuntime/dotnet"
    commands = [[str(dotnet), str(unity / "DotNetSdkRoslyn/csc.dll"), "@" + str(out / "build.rsp")],
                [str(dotnet), str(build / "VisualProbe.dll"), str(out / "input.json"), str(out / "visual-settings.json"),
                 str(out / "mesh-export.json"), str(original_results["radius"])]]
    for i, command in enumerate(commands):
        result = subprocess.run(command, cwd=repo, capture_output=True, text=True, timeout=180)
        (out / (str(i) + ".log")).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise ValueError("三维网格导出失败，见 nonflat-3d 日志")
    raw = read(out / "mesh-export.json")
    original = {row["level_id"]: row for row in selected}
    if len(raw["levels"]) != len(ids) or {row["level_id"] for row in raw["levels"]} != ids:
        raise ValueError("补证关号集合不一致")
    rows = []
    for row in raw["levels"]:
        expected = {(s["kind"], s["source"]): s["mesh_hashes"] for s in original[row["level_id"]]["sources"]}
        actual = {(s["kind"], s["source"]): s["mesh_hashes"] for s in row["sources"]}
        if not expected or actual != expected:
            raise ValueError("补证网格与首轮实际网格不同：" + row["level_id"])
        rows.append(dict(level_id=row["level_id"], sources=[source_checks(s, payload["settings"]) for s in row["sources"]]))
    supplement = dict(schema_version=1, head=head, commands=commands, smoke=smoke(),
                      input_sha256=sha(out / "mesh-export.json"), detector_sha256=sha(Path(__file__).with_name("level_3d_checks.py")),
                      levels=rows)
    for item in manifest["sources"] + manifest["kernel_assemblies"]:
        if sha(Path(item["path"])) != item["sha256"]:
            raise ValueError("补证期间依赖变化")
    save(out / "results.json", supplement)
    # Preserve original summaries before merging; positive hits remain in supplemental evidence.
    for name in ("visual-summary.json", "report-fragment.json"):
        before = out / ("before-" + name)
        if not before.exists():
            shutil.copy2(levels / name, before)
    closed = merge_clear(levels, supplement)
    print("非平面三维补证：", len(rows), "关，新增闭合", len(closed), "关；其余状态保持不变，不转人工。")


if __name__ == "__main__":
    main()
