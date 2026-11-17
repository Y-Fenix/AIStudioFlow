#!/usr/bin/env python3
"""Parse baseline-listed JS/Swift without executing repository code or build hooks."""
import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

TOOLS = {'node': ['--version'], 'swiftc': ['--version']}
LANGUAGES = {'.js': 'node', '.cjs': 'node', '.mjs': 'node', '.swift': 'swiftc'}
SOURCE_SUFFIXES = set(LANGUAGES) | {'.kt', '.kts', '.java', '.ts', '.tsx', '.jsx',
                                  '.cs', '.m', '.mm', '.h', '.py', '.rb', '.sh'}


def clean_environment(source=None):
    source = os.environ if source is None else source
    # Do not inherit preload flags, injected compiler flags or credential variables.
    return {k: v for k, v in source.items()
            if k in {'PATH', 'HOME', 'TMPDIR', 'SystemRoot', 'LANG', 'LC_ALL'}}


def run_process(argv, cwd, timeout):
    start = time.monotonic()
    try:
        with tempfile.TemporaryFile() as output:
            proc = subprocess.Popen(argv, cwd=cwd, env=clean_environment(),
                                    stdout=output, stderr=subprocess.STDOUT,
                                    start_new_session=True)
            timed_out = False
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            output.seek(0)
            diagnostics = output.read(65536).decode('utf-8', errors='replace')
            return {'exit_code': proc.returncode, 'timed_out': timed_out,
                    'duration_seconds': round(time.monotonic() - start, 3),
                    'diagnostics': diagnostics}
    except OSError as error:
        return {'exit_code': None, 'timed_out': False,
                'duration_seconds': round(time.monotonic() - start, 3),
                'diagnostics': '', 'error_type': type(error).__name__}


def source_matches(root, relative, digest):
    path = root / relative
    cursor = path
    while cursor != root:
        if cursor.is_symlink():
            return False
        cursor = cursor.parent
    if root.is_symlink():
        return False
    try:
        return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest
    except OSError:
        return False


def audit(baseline, output, timeout=15, tool_paths=None):
    if timeout <= 0:
        raise ValueError('timeout must be positive')
    output = Path(output).resolve()
    repositories = baseline['repositories']
    # Validate every input before writing output or launching any tool.
    for entry in repositories.values():
        root = Path(entry['root'])
        if not root.is_absolute():
            raise ValueError('repository root must be absolute')
        if output.is_relative_to(root.resolve()):
            raise ValueError('tool output must be outside source repositories')
        for relative in entry['files']:
            p = Path(relative)
            if p.is_absolute() or '..' in p.parts:
                raise ValueError('baseline contains escaping path')
    if output.exists():
        raise ValueError('use a new output directory')
    output.mkdir(parents=True)
    paths = tool_paths if tool_paths is not None else {k: shutil.which(k) for k in TOOLS}
    probes = {}
    for name, version_args in TOOLS.items():
        executable = paths.get(name)
        if executable:
            result = run_process([executable, *version_args], output, timeout)
            # Preserve tool versions only, never raw compiler/source diagnostics.
            versions = re.findall(r'(?:\d+\.)+\d+(?:[-+][\w.]+)?', result['diagnostics'])
            probes[name] = {'path': executable, 'version': versions[:3],
                            'available': result['exit_code'] == 0 and not result['timed_out'],
                            'exit_code': result['exit_code'], 'timed_out': result['timed_out']}
        else:
            probes[name] = {'path': None, 'version': [], 'available': False}
    checks = []
    for repo, entry in repositories.items():
        root = Path(entry['root'])
        if not entry['available']:
            checks.append({'repository': repo, 'path': None, 'status': 'missing_repository'})
            continue
        for relative, digest in sorted(entry['files'].items()):
            suffix = Path(relative).suffix.lower()
            if suffix not in SOURCE_SUFFIXES:
                continue
            row = {'repository': repo, 'path': relative, 'baseline_sha256': digest,
                   'check': 'syntax_only', 'command': None, 'exit_code': None}
            checks.append(row)
            tool = LANGUAGES.get(suffix)
            if not source_matches(root, relative, digest):
                row['status'] = 'stale'
                continue
            if not tool:
                row.update(status='unsupported', reason='No parser adapter; compilation/lint not executed')
                continue
            if not probes[tool]['available']:
                row.update(status='unavailable', tool=tool)
                continue
            argv = [paths[tool], *(['--check'] if tool == 'node' else ['-frontend', '-parse']),
                    str(root / relative)]
            row.update(tool=tool, tool_version=probes[tool]['version'], command=argv)
            result = run_process(argv, output, timeout)
            row.update({k: v for k, v in result.items() if k != 'diagnostics'})
            if not source_matches(root, relative, digest):
                row['status'] = 'stale'
            elif result['timed_out']:
                row['status'] = 'timeout'
            elif result['exit_code'] == 0:
                row['status'] = 'executed_ok'
            elif (tool == 'node' and 'SyntaxError:' in result['diagnostics']) or (
                    tool == 'swiftc' and re.search(r':\d+:\d+: error:', result['diagnostics'])):
                row['status'] = 'syntax_error'
            else:
                row['status'] = 'tool_error'
            # Diagnostics may quote credentials from source. Store locations only;
            # confirm the exact error through a targeted, redacted source read.
            pattern = re.escape(str(root / relative)) + r':(\d+)(?::(\d+))?'
            row['diagnostic_locations'] = [
                {'line': int(line), 'column': int(col) if col else None}
                for line, col in re.findall(pattern, result['diagnostics'])][:50]
    counts = dict(Counter(row['status'] for row in checks))
    payload = {'schema_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
               'mode': 'syntax_only', 'tools': probes, 'checks': checks, 'counts': counts,
               'complete': bool(checks) and all(r['status'] == 'executed_ok' for r in checks)
                           and all(not e.get('errors') for e in repositories.values()),
               'baseline_errors': {k: len(v.get('errors', [])) for k, v in repositories.items()},
               'coverage_boundary': 'Only baseline-listed JS/Swift files parsed; no type checking, lint, builds, runtime tests or proof of loop termination.',
               'release_verified': False}
    with (output / 'tool-results.json').open('x') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--output', required=True, help='New directory outside all source roots')
    parser.add_argument('--timeout', type=float, default=15)
    args = parser.parse_args()
    result = audit(json.loads(Path(args.baseline).read_text()), args.output, args.timeout)
    print(json.dumps({'result': str(Path(args.output).resolve() / 'tool-results.json'),
                      'counts': result['counts'], 'complete': result['complete']}, ensure_ascii=False))
    # 2: detected parse errors; 3: partial/tool failure; 0: all inventoried source checks succeeded.
    return 2 if result['counts'].get('syntax_error') else (0 if result['complete'] else 3)


if __name__ == '__main__':
    raise SystemExit(main())
