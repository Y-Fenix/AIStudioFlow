#!/usr/bin/env python3
"""Run an authorized local check and bind its raw output to this audit baseline.

This wrapper is not a sandbox. The host must inspect the command's side effects
and supply actual production/input dependencies, not only a test harness file.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inside(root, path):
    value = (root / path).resolve()
    if not value.is_relative_to(root) or not value.is_file():
        raise ValueError("依赖不存在或越出允许目录：" + str(path))
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source", action="append", required=True, help="实际生产/输入依赖，仓库相对路径，可重复")
    parser.add_argument("--output", action="append", default=[], help="本命令应生成的证据目录相对文件，可重复")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    root, out = args.root.resolve(), args.evidence_dir.resolve()
    if not out.is_dir() or not out.is_relative_to(root / "QA/results"):
        raise ValueError("evidence-dir 必须是当前仓库 QA/results 的本轮目录")
    if not args.run_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in args.run_id):
        raise ValueError("run-id 只允许字母、数字、连字符和下划线")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.timeout <= 0:
        raise ValueError("缺实际命令或超时无效")
    baseline = json.loads((out / "baseline.json").read_text(encoding="utf-8"))
    head = lambda: subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=root, text=True).strip()
    if Path(baseline["root"]).resolve() != root or baseline["head"] != head() or baseline["branch"] != branch:
        raise ValueError("当前仓库、分支或 HEAD 不匹配本轮基线")
    inputs = {inside(root, p).relative_to(root).as_posix(): digest(inside(root, p)) for p in args.source}
    for name in args.output:
        candidate = (out / name).resolve()
        if not candidate.is_relative_to(out) or candidate.exists():
            raise ValueError("预期产物必须是本轮尚不存在的新文件，不能给旧产物补签：" + name)
    folder = out / "execution" / args.run_id
    folder.mkdir(parents=True, exist_ok=False)
    log, receipt = folder / "stdout.log", folder / "receipt.json"
    result = dict(schema_version=1, run_id=args.run_id, baseline_run_id=baseline["run_id"],
                  command=command, workdir=str(root), head_before=head(), branch=branch,
                  started_at=datetime.now(timezone.utc).isoformat(), state="running", inputs=inputs,
                  log=log.relative_to(out).as_posix(), exit_code=None, outputs={}, changed_inputs=[])

    def save():
        receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    save()
    with log.open("w", encoding="utf-8") as stream:
        try:
            process = subprocess.Popen(command, cwd=root, stdout=stream, stderr=subprocess.STDOUT)
            try:
                code = process.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                # Only this command's process is owned here; no Editor/service termination.
                process.kill()
                process.wait()
                result["failure"] = "命令超过本轮预算，已停止本 wrapper 启动的直接进程；子进程状态须由总控核对"
                code = 124
                result["state"] = "unknown"
        except OSError as exc:
            stream.write(str(exc) + "\n")
            code = 127
        if result["state"] == "running":
            result["state"] = "finished"
    result.update(exit_code=code, ended_at=datetime.now(timezone.utc).isoformat(),
                  head_after=head(), log_sha256=digest(log))
    result["changed_inputs"] = [p for p, old in inputs.items() if not (root / p).is_file() or digest(root / p) != old]
    for name in args.output:
        try:
            output = inside(out, name)
            result["outputs"][output.relative_to(out).as_posix()] = digest(output)
        except ValueError as exc:
            result.setdefault("missing_outputs", []).append(str(exc))
    save()
    print(json.dumps(dict(id=args.run_id, command=command, exit_code=code,
                          evidence=result["log"], execution_receipt=receipt.relative_to(out).as_posix()), ensure_ascii=False))
    return code if code else 2 if result["changed_inputs"] or result.get("missing_outputs") else 0


if __name__ == "__main__":
    sys.exit(main())
