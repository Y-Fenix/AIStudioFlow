#!/usr/bin/env python3
"""Package this project skill only; exclude reports, bytecode and private caches."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    skill = Path(__file__).resolve().parents[1]
    profile = json.loads((skill / "assets/delivery-profile.json").read_text())
    template = skill / "assets/report-template.html"
    if hashlib.sha256(template.read_bytes()).hexdigest() != profile["template_sha256"]:
        raise ValueError("模板与已确认版本不一致")
    if hashlib.sha256((skill / 'assets/bug-columns.json').read_bytes()).hexdigest() != profile['bug_columns_sha256']:
        raise ValueError('Bug 表头与已确认版本不一致')
    target = args.output.resolve()
    if target.is_relative_to(skill):
        raise ValueError("分发包不能生成在 skill 内部")
    files = [p for p in skill.rglob("*") if p.is_file() and not p.is_symlink()
             and not any(s in {"__pycache__", ".DS_Store"} for s in p.relative_to(skill).parts)
             and p.suffix not in {".pyc", ".pyo"}]
    target.parent.mkdir(parents=True, exist_ok=True)
    hashes = {}
    # Never silently overwrite an earlier distribution.
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            name = (Path('gagasort-qa') / path.relative_to(skill)).as_posix()
            raw = path.read_bytes()
            archive.writestr(name, raw)
            hashes[name] = hashlib.sha256(raw).hexdigest()
        archive.writestr("package-manifest.json", json.dumps(dict(profile=profile, files=hashes), ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(dict(output=str(target), files=len(files), workflow_version=profile["workflow_version"],
                          sha256=hashlib.sha256(target.read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == "__main__":
    main()
