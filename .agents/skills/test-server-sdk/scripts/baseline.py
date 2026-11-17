#!/usr/bin/env python3
"""Record local source hashes only; never execute repository code or contact services."""
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/Users/yf/Documents/Unity/SDK&服务器')
DEFAULTS = {k: str(ROOT / v) for k, v in {
    'android': 'bbsdkunity-android', 'ios': 'bbsdkunity-ios',
    'sdkserver': 'sdkserver', 'gameserver': 'server',
}.items()}
EXCLUDED = {'.git', 'node_modules', 'Pods', '.gradle', 'build', 'dist',
            'Library', 'Temp', 'obj', 'bin', '__pycache__', '.venv',
            '静态检查报告'}
EXTENSIONS = {'.js', '.cjs', '.mjs', '.ts', '.json', '.swift', '.kt', '.java',
              '.cs', '.m', '.mm', '.h', '.xml', '.plist', '.entitlements',
              '.gradle', '.kts', '.properties', '.yaml', '.yml', '.sql', '.md',
              '.lock', '.toml', '.xcconfig', '.pbxproj', '.sh', '.py',
              '.podspec', '.rb', '.txt', '.xcprivacy', '.conf', '.config'}
NAMES = {'Podfile', 'Gemfile', 'Package.swift', 'Dockerfile', 'Makefile',
         'gradlew', '.gitmodules', '.gitignore'}


def snapshot(roots):
    repos = {}
    for key, raw in roots.items():
        root = Path(raw).expanduser().resolve()
        entry = {'root': str(root), 'available': root.is_dir(), 'files': {},
                 'skipped': [], 'errors': []}
        repos[key] = entry
        if not entry['available']:
            continue
        def onerror(error):
            entry['errors'].append(str(error))
        for folder, dirs, files in os.walk(root, onerror=onerror, followlinks=False):
            for name in list(dirs):
                p = Path(folder) / name
                if name in EXCLUDED or p.is_symlink():
                    entry['skipped'].append(str(p.relative_to(root)) + '/')
                    dirs.remove(name)
            dirs.sort()
            for name in sorted(files):
                path = Path(folder) / name
                relative = str(path.relative_to(root))
                if path.suffix.lower() not in EXTENSIONS and name not in NAMES:
                    entry['skipped'].append(relative)
                    continue
                try:
                    if path.is_symlink() or not path.is_file():
                        entry['skipped'].append(relative)
                        continue
                    before = path.stat()
                    digest = hashlib.sha256()
                    with path.open('rb') as handle:
                        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                            digest.update(chunk)
                    after = path.stat()
                    if (before.st_mtime_ns, before.st_size, before.st_ino) != (
                            after.st_mtime_ns, after.st_size, after.st_ino):
                        entry['errors'].append(relative + ': changed during read')
                    entry['files'][relative] = digest.hexdigest()
                except OSError as error:
                    entry['errors'].append(relative + ': ' + str(error))
        entry['skipped'].sort()
    return repos


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    capture = sub.add_parser('capture')
    capture.add_argument('--output', required=True)
    capture.add_argument('--roots', help='JSON mapping of four repository IDs to absolute paths')
    verify = sub.add_parser('verify')
    verify.add_argument('--input', required=True)
    args = parser.parse_args()
    if args.mode == 'capture':
        roots = json.loads(Path(args.roots).read_text()) if args.roots else DEFAULTS
        if (not isinstance(roots, dict) or set(roots) != set(DEFAULTS)
                or any(not isinstance(v, str) or not Path(v).is_absolute()
                       for v in roots.values())):
            parser.error('roots must map android, ios, sdkserver, gameserver to absolute paths')
        target = Path(args.output).expanduser().resolve()
        for raw in roots.values():
            if target.is_relative_to(Path(raw).expanduser().resolve()):
                parser.error('baseline must be outside the four source repositories')
        repos = snapshot(roots)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {'schema_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
                   'policy': {'excluded_directories': sorted(EXCLUDED),
                              'extensions': sorted(EXTENSIONS), 'names': sorted(NAMES),
                              'symlinks': 'excluded'}, 'repositories': repos}
        with target.open('x', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
        print(json.dumps({'baseline': str(target), 'repositories': {
            k: {'available': v['available'], 'files': len(v['files']),
                'skipped': len(v['skipped']), 'errors': len(v['errors'])}
            for k, v in repos.items()}}, ensure_ascii=False))
        return int(any(v['errors'] for v in repos.values()))
    saved = json.loads(Path(args.input).read_text())
    old = saved['repositories']
    current = snapshot({k: v['root'] for k, v in old.items()})
    changed = [k for k in old if old[k] != current[k]
               or old[k]['errors'] or current[k]['errors']]
    print(json.dumps({'stable': not changed, 'changed_repositories': changed,
                      'release_verified': False}, ensure_ascii=False))
    return int(bool(changed))


if __name__ == '__main__':
    raise SystemExit(main())
