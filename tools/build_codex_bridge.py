"""Build a per-architecture client Mac bridge archive; never install or launch it."""
import argparse
import hashlib
import os
import platform
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile


def build_bridge(output):
    architecture = platform.machine()
    if platform.system() != 'Darwin' or architecture not in ('arm64', 'x86_64'):
        raise ValueError('桥接构建需要 Apple Silicon 或 Intel Mac')
    compiler = shutil.which('swiftc')
    if not compiler:
        raise ValueError('构建机器需要 Xcode Command Line Tools；使用成品的团队成员不需要安装编译器')
    source = Path(__file__).resolve().parent.parent / 'deploy/mac/codex-bridge'
    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    filename = 'StudioFlowCodexBridge-' + architecture + '.zip'
    with tempfile.TemporaryDirectory(prefix='.bridge-build-', dir=output) as temp:
        bundle = Path(temp) / 'StudioFlow Codex Bridge.app'
        executable = bundle / 'Contents/MacOS/StudioFlowCodexBridge'
        executable.parent.mkdir(parents=True)
        shutil.copy2(source / 'Info.plist', bundle / 'Contents/Info.plist')
        subprocess.run([compiler, '-parse-as-library', '-target', architecture+'-apple-macosx13.0',
                        '-framework', 'AppKit', str(source/'BridgeURLPolicy.swift'),
                        str(source/'BridgeComposer.swift'),
                        str(source/'main.swift'), '-o', str(executable)], check=True)
        executable.chmod(0o755)
        # Ad-hoc signing seals the local bundle; this is not Developer ID signing
        # or notarization and is never represented as a trusted public release.
        subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(bundle)], check=True,
                       capture_output=True, text=True)
        staged_archive = Path(temp) / filename
        with zipfile.ZipFile(staged_archive, 'w', zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(bundle.rglob('*')):
                if file.is_file():
                    archive.write(file, file.relative_to(Path(temp)))
        final_archive = output / filename
        os.replace(staged_archive, final_archive)
    checksum = hashlib.sha256(final_archive.read_bytes()).hexdigest()
    (output / (filename + '.sha256')).write_text(checksum + '  ' + filename + '\n', encoding='utf-8')
    return {'archive': str(final_archive), 'architecture': architecture, 'sha256': checksum}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent.parent/'dist/codex-bridge')
    args = parser.parse_args()
    result = build_bridge(args.output)
    print('已构建：' + result['archive'])
    print('架构：' + result['architecture'] + '；最低 macOS 13；仅本机临时签名，未公证。')
    print('SHA-256：' + result['sha256'])
    print('未安装、启动应用或操作剪贴板。')


if __name__ == '__main__':
    main()
