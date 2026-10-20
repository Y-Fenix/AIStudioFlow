"""Generate reviewable Mac deployment files using actual paths; never installs services."""
import argparse
import grp
import json
import os
from pathlib import Path
import plistlib
import pwd
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit


LABEL = 'com.studioflow.server'


def site_origin(value):
    if not isinstance(value, str) or any(ord(c) <= 32 for c in value):
        raise ValueError('请提供不含空白的真实 HTTPS 域名')
    parsed = urlsplit(value)
    host = parsed.hostname or ''
    if (parsed.scheme != 'https' or parsed.netloc.lower() != host.lower()
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment
            or len(host) > 253 or '.' not in host
            or not all(re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', part) for part in host.split('.'))):
        raise ValueError('请提供固定 HTTPS 域名，不带账号、端口、路径或查询参数')
    if (host in ('example.com', 'example.net', 'example.org')
            or any(host.endswith('.'+suffix) for suffix in ('example.com', 'example.net', 'example.org'))
            or host.endswith(('.localhost', '.invalid', '.test'))):
        raise ValueError('请使用目标团队域名，不能保留示例域名')
    return 'https://' + host.lower()


def runtime_path(value):
    executable = Path(value).expanduser().resolve()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError('Python 路径不存在或不可执行')
    try:
        raw = subprocess.check_output([str(executable), '-c', 'import json,sys;print(json.dumps(list(sys.version_info[:3])))'],
                                      stderr=subprocess.DEVNULL, timeout=10, text=True)
        version = json.loads(raw)
        if not isinstance(version, list) or len(version) != 3 or tuple(version) < (3, 11, 0):
            raise ValueError()
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        raise ValueError('请使用可运行的 Python 3.11 或更高版本') from None
    return executable


def prepare_deployment(*, app_root, public_url, service_user, output_dir, python_path=None,
                       data_dir=None, log_dir=None, codex_home=None):
    """Return a new private folder. Existing output/runtime files are never overwritten."""
    origin = site_origin(public_url)
    if not isinstance(service_user, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]{0,63}', service_user):
        raise ValueError('服务账号名称无效')
    try:
        account = pwd.getpwnam(service_user)
    except KeyError:
        raise ValueError('服务账号不存在；请先在目标 Mac 创建专用标准账号') from None
    if account.pw_uid == 0:
        raise ValueError('服务账号不能使用 root')
    app = Path(app_root).expanduser().resolve()
    if not (app/'server/app.py').is_file() or not (app/'web/index.html').is_file():
        raise ValueError('代码目录必须包含 server/app.py 与 web/index.html')
    executable = runtime_path(python_path or sys.executable)
    account_home = Path(account.pw_dir)
    if not account_home.is_absolute():
        raise ValueError('服务账号没有有效的绝对主目录')
    data = Path(data_dir).expanduser().resolve() if data_dir else account_home/'Library/Application Support/StudioFlow'
    logs = Path(log_dir).expanduser().resolve() if log_dir else account_home/'Library/Logs/StudioFlow'
    codex = Path(codex_home).expanduser().resolve() if codex_home else account_home/'.codex'
    output = Path(output_dir).expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError('输出目录已存在，请指定新目录；不会覆盖已生成的配置')
    config = {
        'Label': LABEL, 'UserName': service_user,
        'ProgramArguments': [str(executable), '-m', 'server.app', '--host', '127.0.0.1', '--port', '8766', '--database', str(data/'platform.sqlite')],
        'WorkingDirectory': str(app),
        'EnvironmentVariables': {'HOME': str(account_home), 'CODEX_HOME': str(codex),
                                 'PATH': os.pathsep.join(dict.fromkeys((str(executable.parent), '/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin')))},
        'RunAtLoad': True, 'KeepAlive': True, 'ProcessType': 'Background',
        'StandardOutPath': str(logs/'server.log'), 'StandardErrorPath': str(logs/'server-error.log'),
    }
    metadata = {'public_url': origin, 'auth_mode': 'password',
                'app_root': str(app), 'python': str(executable), 'service_user': service_user,
                'database': str(data/'platform.sqlite'), 'auth_config': str(data/'team-auth.json'),
                'codex_home': str(codex), 'log_dir': str(logs)}
    quote = shlex.quote
    group = grp.getgrgid(account.pw_gid).gr_name
    plist = output/(LABEL+'.plist')
    instructions = f'''# 当前 Mac 的部署文件

这是生成结果，尚未安装服务。核对服务账号 {service_user} 为专用标准账号，能读取代码与 Python，并能访问所选模型服务。

站点：{origin}
登录方式：本地账号与密码（无需飞书应用）
数据库：{metadata['database']}
模型配置目录：{codex}

## 准备运行目录（需要系统管理员权限）

```sh
sudo install -d -o {quote(service_user)} -g {quote(group)} -m 700 {quote(str(data))} {quote(str(logs))}
```

代码目录保持发布者维护；服务账号只写数据与日志目录。所选 CODEX_HOME 属于服务账号；也可在平台配置自定义 API。此工具不会复制任何个人凭据。

## 配置真实登录

先用同一服务账号、同一数据库启动本机配置页。如果8766已有旧服务，先按发布流程停机备份，避免同时启动。首次迁移旧库使用 SQLite 一致性备份，不直接复制运行中的数据库。

```sh
cd {quote(str(app))}
sudo -u {quote(service_user)} env HOME={quote(str(account_home))} CODEX_HOME={quote(str(codex))} {quote(str(executable))} -m server.app --host 127.0.0.1 --port 8766 --database {quote(str(data/'platform.sqlite'))}
```

在服务器本机浏览器直接打开 http://127.0.0.1:8766/ ，设置负责人账号与密码。此账号保留原有工作室与项目。登录后在“权限后台 → 账号登录与部署”保存上述团队 HTTPS 地址，配置反向代理，再让同事自行注册、由负责人审批。首次设置不可经代理访问。完成后按 Ctrl+C 停止临时服务，再交给 launchd。

## 核对后安装

把 Caddyfile 中的站点合并到维护者的实际 Caddy 配置，不要覆盖已有站点。准备 DNS、80/443 网络与 Caddy，再校验并启用 HTTPS。先运行只读预检；通过不代表真实登录或网络已验证。

```sh
cd {quote(str(app))}
python3 tools/mac_preflight.py --plist {quote(str(plist))} --caddyfile {quote(str(output/'Caddyfile'))} --auth-config {quote(str(data/'team-auth.json'))}
caddy validate --config {quote(str(output/'Caddyfile'))}
sudo install -o root -g wheel -m 644 {quote(str(plist))} /Library/LaunchDaemons/{LABEL}.plist
sudo plutil -lint /Library/LaunchDaemons/{LABEL}.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/{LABEL}.plist
sudo launchctl print system/{LABEL}
```

已有同名服务时先按发布流程停机备份，不要重复 bootstrap。数据库、私密配置和日志不加入 Git。详见代码目录 docs/mac-team-deployment.md。
'''
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.studioflow-deploy-', dir=output.parent))
    try:
        files = {LABEL+'.plist': plistlib.dumps(config), 'Caddyfile': (origin.removeprefix('https://')+' {\n\tencode zstd gzip\n\treverse_proxy 127.0.0.1:8766\n}\n').encode(),
                 'deployment.json': (json.dumps(metadata, ensure_ascii=False, indent=2)+'\n').encode(), 'DEPLOY.md': instructions.encode()}
        for name, content in files.items():
            fd = os.open(staging/name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as handle:
                handle.write(content)
        if output.exists() or output.is_symlink():
            raise FileExistsError('输出目录已存在；不会覆盖现有配置')
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return output


def main():
    parser = argparse.ArgumentParser(description='按实际 Mac 路径生成部署文件；不安装、不启动服务、不读取密钥。')
    parser.add_argument('--public-url', required=True, help='团队固定 HTTPS 站点地址')
    parser.add_argument('--service-user', required=True, help='已存在的非 root 专用服务账号')
    parser.add_argument('--output', required=True, help='新的输出目录，不覆盖已有目录')
    parser.add_argument('--app-root', default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--python', default=sys.executable, dest='python_path')
    parser.add_argument('--data-dir')
    parser.add_argument('--log-dir')
    parser.add_argument('--codex-home')
    args = parser.parse_args()
    try:
        folder = prepare_deployment(app_root=args.app_root, public_url=args.public_url, service_user=args.service_user,
                                    output_dir=args.output, python_path=args.python_path, data_dir=args.data_dir,
                                    log_dir=args.log_dir, codex_home=args.codex_home)
    except (ValueError, OSError) as error:
        parser.exit(1, str(error)+'\n')
    print('已生成部署文件：'+str(folder))
    print('请先核对 DEPLOY.md；当前没有安装或启动系统服务。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
