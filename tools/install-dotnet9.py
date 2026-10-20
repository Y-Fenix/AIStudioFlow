"""安装官方 .NET9 SDK到平台独立目录；验证SHA512后解包，不写游戏仓库。"""
import hashlib
import json
import platform
import tempfile
import tarfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / '.runtimes/dotnet'


def install():
    rid = {'Darwin': 'osx', 'Linux':'linux'}.get(platform.system())
    machine = {'arm64':'arm64', 'aarch64':'arm64', 'x86_64':'x64'}.get(platform.machine())
    if not rid or not machine:
        raise ValueError('当前安装器不支持此系统架构')
    rid += '-' + machine
    with urlopen('https://dotnetcli.blob.core.windows.net/dotnet/release-metadata/9.0/releases.json', timeout=30) as response:
        metadata = json.load(response)
    version = metadata['latest-sdk']
    package = None
    for release in metadata['releases']:
        for sdk in release.get('sdks', [release.get('sdk', {})]):
            if sdk.get('version') == version:
                package = next((f for f in sdk['files'] if f['rid'] == rid and f['name'].endswith('.tar.gz')), None)
        if package:
            break
    if not package:
        raise ValueError('官方清单没有匹配的SDK包')
    url = urlsplit(package['url'])
    if url.scheme != 'https' or url.hostname not in ('builds.dotnet.microsoft.com', 'download.visualstudio.microsoft.com'):
        raise ValueError('拒绝非官方SDK下载地址')
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=DESTINATION.parent, prefix='download-') as folder:
        archive = Path(folder)/'sdk.tar.gz'
        digest = hashlib.sha512()
        count = 0
        print(f'下载官方SDK {version} / {rid}', flush=True)
        with urlopen(package['url'],timeout=30) as response, archive.open('wb') as output:
            while chunk := response.read(1024*1024):
                count += len(chunk)
                if count > 350000000:
                    raise ValueError('SDK包超出350MB限制')
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest().lower() != package['hash'].lower():
            raise ValueError('官方SHA512校验失败，不安装')
        with tarfile.open(archive) as bundle:
            bundle.extractall(DESTINATION, filter='data')
    print(f'SDK已验证并安装：{DESTINATION}', flush=True)


if __name__ == '__main__':
    install()
