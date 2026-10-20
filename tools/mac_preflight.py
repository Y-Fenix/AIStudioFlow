"""Read-only preflight checks for a configured StudioFlow Mac deployment."""
import argparse
import json
import os
import plistlib
import re
from pathlib import Path
from urllib.parse import urlsplit


def check_deployment(plist_path, caddy_path, auth_path):
    errors = []
    plist_path, caddy_path, auth_path = map(Path, (plist_path, caddy_path, auth_path))

    try:
        config = plistlib.loads(plist_path.read_bytes())
    except (OSError, plistlib.InvalidFileException, ValueError) as exc:
        return [f'无法读取 launchd plist：{exc}']
    args = config.get('ProgramArguments', [])
    if not isinstance(args, list) or not args:
        errors.append('launchd plist 缺少 ProgramArguments')
        args = []
    if '--host' not in args or args[args.index('--host') + 1:args.index('--host') + 2] != ['127.0.0.1']:
        errors.append('服务必须只绑定 127.0.0.1，由 HTTPS 反向代理提供团队访问')
    if '--database' not in args or not args[args.index('--database') + 1:args.index('--database') + 2]:
        errors.append('launchd plist 缺少数据库绝对路径')
    elif not Path(args[args.index('--database') + 1]).is_absolute():
        errors.append('数据库路径必须是绝对路径')
    working = config.get('WorkingDirectory', '')
    if not working or not Path(working).is_absolute():
        errors.append('WorkingDirectory 必须是绝对路径')
    if any('/opt/studioflow/app' in str(value) or '/Users/_studioflow/' in str(value)
           for value in (working, args)):
        errors.append('launchd plist 仍包含示例目录或服务用户路径占位符')
    if not config.get('UserName') or config.get('UserName') == 'root':
        errors.append('launchd 必须配置专用的非 root 服务用户')

    try:
        caddy = caddy_path.read_text(encoding='utf-8')
    except OSError as exc:
        return errors + [f'无法读取 Caddyfile：{exc}']
    hosts = re.findall(r'(?m)^\s*([A-Za-z0-9.-]+)\s*\{', caddy)
    upstreams = re.findall(r'(?m)^\s*reverse_proxy\s+([^\s]+)', caddy)
    if len(hosts) != 1 or hosts[0] in ('studio.example.com', 'localhost') or any('example' in host for host in hosts):
        errors.append('Caddyfile 必须配置唯一真实站点域名，不能保留示例域名')
    if not upstreams or any(upstream not in ('127.0.0.1:8766', 'localhost:8766') for upstream in upstreams):
        errors.append('Caddy 反向代理必须指向本机 127.0.0.1:8766')

    try:
        auth = json.loads(auth_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        return errors + [f'无法读取服务器认证配置：{exc}']
    try:
        mode = os.stat(auth_path).st_mode & 0o777
        if mode != 0o600:
            errors.append('team-auth.json 权限必须为 0600')
    except OSError as exc:
        errors.append(f'无法检查认证配置文件权限：{exc}')
    if auth.get('mode') not in ('team', 'password'):
        errors.append('团队部署前必须启用 password 本地账号认证')
    if auth.get('mode') == 'team' and (not auth.get('client_id') or not auth.get('client_secret')):
        errors.append('团队登录缺少飞书 Client ID 或 Secret')
    public_url = auth.get('public_url', '')
    parsed = urlsplit(public_url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        errors.append('public_url 必须是无路径的 HTTPS 站点地址')
    elif len(hosts) == 1 and hosts[0] != parsed.hostname:
        errors.append('Caddy 域名必须与 public_url 域名一致')
    tenants = auth.get('allowed_tenants')
    if auth.get('mode') == 'team' and auth.get('allow_all_tenants') is not True and (not isinstance(tenants, list) or not tenants):
        errors.append('请配置至少一个允许登记的飞书企业，或明确启用所有企业登记')
    return errors


def main():
    parser = argparse.ArgumentParser(description='只读检查 StudioFlow Mac 团队部署配置；不安装、不启动服务。')
    parser.add_argument('--plist', required=True, help='已替换占位符的 launchd plist 路径')
    parser.add_argument('--caddyfile', required=True, help='实际使用的 Caddyfile 路径')
    parser.add_argument('--auth-config', required=True, help='服务器私有 team-auth.json 路径')
    args = parser.parse_args()
    errors = check_deployment(args.plist, args.caddyfile, args.auth_config)
    if errors:
        for error in errors:
            print('FAIL:', error)
        return 1
    print('PASS: launchd、Caddy、团队认证配置结构与安全边界检查通过。')
    print('未检查负责人账号初始化、TLS 证书签发、launchd 运行状态或目标 Mac 网络可达性。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
