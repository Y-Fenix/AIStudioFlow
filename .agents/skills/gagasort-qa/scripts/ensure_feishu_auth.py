#!/usr/bin/env python3
"""Ensure the local lark-cli session has the scope needed by the report.

This command is run before the audit. It may open the Feishu verification page
and returns the verification link immediately when authorization is needed.
It never prints or persists an access token.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen


from feishu_bridge import REQUIRED_SCOPES, BRIDGE_PROTOCOL
REQUIRED_SCOPE_TEXT = " ".join(REQUIRED_SCOPES)


def env() -> dict[str, str]:
    value = os.environ.copy()
    value["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
    value["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
    return value


def envelope(stdout: str, stderr: str = "") -> dict:
    for candidate in [stdout.strip(), *[line.strip() for line in stdout.splitlines() if line.lstrip().startswith("{")]]:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise RuntimeError((stderr or stdout or "lark-cli 没有返回 JSON").strip()[-2000:])


def run(cli: str, args: list[str], timeout: int = 60) -> dict:
    result = subprocess.run([cli, *args], text=True, capture_output=True, timeout=timeout, env=env())
    value = envelope(result.stdout if result.returncode == 0 else result.stderr, result.stdout)
    if result.returncode != 0 or value.get("ok") is False:
        raise RuntimeError(value.get("error", {}).get("message", "飞书 CLI 请求失败"))
    return value


def is_ready(cli: str) -> bool:
    try:
        status = run(cli, ["auth", "status", "--json"])
        user = status.get("identities", {}).get("user", {})
        scopes = set(str(user.get("scope", "")).split())
        return user.get("tokenStatus") in {"valid", "needs_refresh"} and set(REQUIRED_SCOPES).issubset(scopes)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return False


def make_qr(cli: str, verification_url: str, output: Path) -> bool:
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run([cli, "auth", "qrcode", verification_url, "--output", output.name, "--size", "256"],
                                cwd=output.parent, text=True, capture_output=True, timeout=30, env=env())
        return result.returncode == 0 and output.is_file()
    except (OSError, subprocess.TimeoutExpired):
        return False


def start(cli: str, qr_path: Path) -> int:
    result = run(cli, ["auth", "login", "--scope", REQUIRED_SCOPE_TEXT, "--no-wait", "--json"])
    data = result.get("data", {}) if isinstance(result.get("data"), dict) else {}
    verification_url = data.get("verification_url") or result.get("verification_url")
    device_code = data.get("device_code") or result.get("device_code")
    if not verification_url or not device_code:
        raise RuntimeError("飞书 CLI 未返回 verification_url/device_code")
    qr_ready = make_qr(cli, str(verification_url), qr_path)
    # Return immediately: the Agent must show the URL/QR before completing login.
    print(json.dumps({"status": "authorization_required", "verification_url": verification_url,
                      "device_code": device_code, "qr_path": str(qr_path) if qr_ready else ""}, ensure_ascii=False), flush=True)
    return 3


def bridge_is_ready(port: int) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
            value = json.loads(response.read().decode("utf-8"))
        return value.get("ok") is True and value.get("service") == "gagasort-feishu-bridge" and value.get("protocol") == BRIDGE_PROTOCOL
    except Exception:  # noqa: BLE001 - an unavailable port is the normal path
        return False


def ensure_bridge(cli: str, port: int) -> bool:
    if bridge_is_ready(port):
        print(f"飞书桥接已在 http://127.0.0.1:{port} 运行。", flush=True)
        return True
    bridge_script = Path(__file__).with_name("feishu_bridge.py")
    log_path = Path(tempfile.gettempdir()) / "gagasort-feishu-bridge.log"
    try:
        log = log_path.open("a", encoding="utf-8")
        subprocess.Popen(
            [sys.executable, str(bridge_script), "--host", "127.0.0.1", "--port", str(port), "--cli", cli],
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env(),
            start_new_session=True,
        )
    except OSError as exc:
        print(f"飞书桥接启动失败：{exc}", file=sys.stderr)
        return False
    for _ in range(25):
        if bridge_is_ready(port):
            print(f"飞书桥接已启动：http://127.0.0.1:{port}。", flush=True)
            return True
        time.sleep(0.2)
    print(f"飞书桥接未在预期时间内启动，日志：{log_path}", file=sys.stderr)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", default="lark-cli")
    parser.add_argument("--qr", type=Path, default=None, help="二维码输出路径；默认使用临时目录")
    parser.add_argument("--start-bridge", action="store_true", help="授权后自动启动本机 HTML 提单桥接")
    parser.add_argument("--bridge-port", type=int, default=17321)
    parser.add_argument("--device-code", help="仅在用户完成本次授权后继续，设备码不落盘")
    args = parser.parse_args()
    if not shutil.which(args.cli) and not Path(args.cli).exists():
        print("未找到 lark-cli；跳过飞书前置授权，报告仍可导出 CSV。", file=sys.stderr)
        return 2
    if args.device_code:
        try:
            run(args.cli, ["auth", "login", "--device-code", args.device_code, "--json"], timeout=60)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            print(f"飞书授权尚未完成：{exc}", file=sys.stderr)
            return 2
    if is_ready(args.cli):
        print("飞书授权已存在，继续执行 skill。")
        return 0 if not args.start_bridge or ensure_bridge(args.cli, args.bridge_port) else 2
    qr = args.qr or Path(tempfile.gettempdir()) / "gagasort-feishu-auth.png"
    try:
        result = start(args.cli, qr)
        if result == 0 and args.start_bridge and not ensure_bridge(args.cli, args.bridge_port):
            return 2
        return result
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"飞书前置授权失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
