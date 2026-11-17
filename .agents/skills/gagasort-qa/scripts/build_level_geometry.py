#!/usr/bin/env python3
"""Compile and run the production rectangle/CP geometry subset without Unity or Library.

Input: {"levels":[{"level_id":1,"board_size":20,"nodes":[[0,0]],
"slots":[{"id":1,"anchor":[10,4],"cp":[10,10],"width":2,"length":4,
"direction":0,"rear":false}]}]}. A single level object is also accepted.
rear: false/0 ordinary; true unknown rear; positive integer references a front slot id.
Per-level skip_geometry=true reports node and CP boundaries but skips all pool rectangles.
Output contains facts, not a full-validator or solvability verdict. Pools may be outside
the board in production. Node containment does not stand in for sampled spline checks.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


def extract_enum(source):
    match = re.search(r"    public enum EGagaSortDirection : byte \{.*?\n    \}", source, re.S)
    if not match:
        raise RuntimeError("production EGagaSortDirection declaration not found")
    return "namespace GagaSort {\n" + match.group() + "\n}\n", match.start(), match.end()


def extract_pool(source):
    start = source.index("    public static class GagaSortPoolGeometry {")
    brace = source.index("{", start)
    depth = 1
    end = brace + 1
    while depth and end < len(source):
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    if depth:
        raise RuntimeError("production pool geometry braces are not balanced")
    return "using System;\nusing System.Collections.Generic;\nnamespace GagaSort {\n" + source[start:end] + "\n}\n", start, end


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="absolute game repository root")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--unity-contents", type=Path)
    parser.add_argument("--self-test", action="store_true", help="only run the production-kernel assertions")
    args = parser.parse_args()
    if not args.input and not args.self_test:
        parser.error("--input or --self-test is required")
    repo = args.repo.resolve()
    project = repo / "GagaSort"
    runtime = project / "Assets/Scripts/GamePlay/GagaSort/Runtime"
    version = (project / "ProjectSettings/ProjectVersion.txt").read_text().splitlines()[0].split(":", 1)[1].strip()
    unity = args.unity_contents or Path("/Applications/Unity/Hub/Editor") / version / "Unity.app/Contents"
    dotnet = unity / "NetCoreRuntime/dotnet"
    compiler = unity / "DotNetSdkRoslyn/csc.dll"
    shared = sorted((unity / "NetCoreRuntime/shared/Microsoft.NETCore.App").glob("6.*"),
                    key=lambda path: tuple(map(int, path.name.split("."))))
    if not shared or not dotnet.is_file() or not compiler.is_file():
        raise RuntimeError("Unity .NET 6 runtime/compiler not found; no Unity process will be started")
    annotations = project / "Assets/Packages/MessagePack.Annotations.3.1.4/lib/netstandard2.0/MessagePack.Annotations.dll"
    if not annotations.is_file():
        raise RuntimeError("production MessagePack annotations DLL not found")
    args.evidence.mkdir(parents=True, exist_ok=True)
    geometry = runtime / "Data/GagaSortGridGeometry.cs"
    utility = runtime / "Logic/GagaSortGridGeometryUtility.cs"
    pool = runtime / "Logic/GagaSortPoolGeometry.cs"
    enums = runtime / "Data/GagaSortEnums.cs"
    probe = Path(__file__).with_name("level_geometry_probe.cs")
    manifest = {"scope": "production rectangle and checkpoint anchor kernels; no splines, relation resolver, Validator or Solver",
                "sources": [], "runtime": str(shared[-1]), "compiler": str(compiler)}
    with tempfile.TemporaryDirectory(prefix="gagasort-geometry-") as temporary:
        build = Path(temporary)
        generated = []
        for source, extractor, name in ((pool, extract_pool, "PoolGeometry.Extracted.cs"),
                                         (enums, extract_enum, "Direction.Extracted.cs")):
            original = source.read_text()
            content, start, end = extractor(original)
            target = build / name
            target.write_text(content)
            generated.append(target)
            # Retain the exact production slice and its line span for review and replay.
            (args.evidence / name).write_text(content)
            manifest["sources"].append({"path": str(source.relative_to(repo)),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "extracted_lines": [original.count("\n", 0, start) + 1, original.count("\n", 0, end) + 1],
                "compiled_slice_sha256": hashlib.sha256(content.encode()).hexdigest()})
        dto = build / "GeometryDtos.cs"
        dto.write_text("""using System.Collections.Generic;
namespace GagaSort {
    // Field-only adapter for the unchanged production PoolGeometry methods.
    public sealed class GagaSortLevelData { public List<GagaSortSlotLevelData> Slots; }
    public sealed class GagaSortSlotLevelData {
        public int SlotId, WidthCells, LengthCells, BlockingEmitterSlotId;
        public GagaSortGridPosition AnchorPosition, CheckPointPosition;
        public EGagaSortDirection ExitDirection;
    }
}
""")
        for source in (geometry, utility, probe, annotations):
            source_path = (str(source.relative_to(repo)) if source.is_relative_to(repo)
                           else str(source.resolve()))
            manifest["sources"].append({"path": source_path,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "compiled_whole": True})
        manifest["adapter_sha256"] = hashlib.sha256(dto.read_bytes()).hexdigest()
        assembly = build / "LevelGeometryProbe.dll"
        response = build / "compile.rsp"
        lines = ["-noconfig", "-nostdlib+", "-target:exe", "-langversion:latest", "-main:LevelGeometryProbe",
                 '-out:"' + str(assembly) + '"']
        lines += ['-r:"' + str(path) + '"' for path in sorted(shared[-1].glob("*.dll"))]
        lines += ['-r:"' + str(annotations) + '"']
        lines += ['"' + str(path) + '"' for path in (geometry, utility, probe, dto, *generated)]
        response.write_text("\n".join(lines) + "\n")
        result = subprocess.run([str(dotnet), str(compiler), "@" + str(response)], cwd=repo,
                                capture_output=True, text=True)
        (args.evidence / "compile.log").write_text(result.stdout + result.stderr)
        manifest["compile_exit_code"] = result.returncode
        (args.evidence / "source-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        if result.returncode:
            raise RuntimeError("geometry compilation failed: " + result.stdout + result.stderr)
        shutil.copy2(annotations, build / annotations.name)
        assembly.with_suffix(".runtimeconfig.json").write_text(json.dumps({"runtimeOptions": {
            "tfm": "net6.0", "framework": {"name": "Microsoft.NETCore.App", "version": shared[-1].name}}}))
        check = subprocess.run([str(dotnet), str(assembly), "--self-test"], cwd=repo, capture_output=True, text=True)
        (args.evidence / "self-test.json").write_text(check.stdout)
        (args.evidence / "self-test.stderr.log").write_text(check.stderr)
        if check.returncode:
            raise RuntimeError("production geometry assertions failed: " + check.stderr)
        if args.self_test:
            output = check.stdout
        else:
            result = subprocess.run([str(dotnet), str(assembly), str(args.input.resolve())], cwd=repo,
                                    capture_output=True, text=True)
            (args.evidence / "run.stderr.log").write_text(result.stderr)
            if result.returncode:
                raise RuntimeError("geometry probe failed: " + result.stderr)
            output = result.stdout
        if args.output:
            args.output.write_text(output)
        else:
            sys.stdout.write(output)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
