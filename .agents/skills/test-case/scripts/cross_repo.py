#!/usr/bin/env python3
"""Bound declared local sources and a static assertion ledger. Never executes tests/services."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def need(value, message):
    if not value:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source(root, relative):
    need(isinstance(relative, str) and relative and not Path(relative).is_absolute(), 'relative source path required')
    path = (root / relative).resolve()
    need(path.is_relative_to(root), 'source outside repository: ' + relative)
    return path


def git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def validate_profile(profile):
    need(profile.get('schema_version') == 1 and profile.get('project'), 'invalid profile')
    repos = profile.get('repositories')
    need(isinstance(repos, dict) and repos, 'repositories required')
    targets = profile.get('targets')
    need(isinstance(targets, list) and targets, 'targets required')
    ids = [t['id'] for t in targets]
    need(all(ids) and len(ids) == len(set(ids)), 'duplicate/empty target id')
    for target in targets:
        need(target.get('domain') in {'iap', 'tracking', 'ads', 'installation'}, 'invalid target domain')
        required = target.get('repositories')
        need(isinstance(required, list) and required and set(required) <= repos.keys(), 'invalid target repositories')


def snapshot(profile, roots, extra, run_id):
    validate_profile(profile)
    need(isinstance(run_id, str) and run_id.strip(), 'run_id required')
    need(not (set(roots) | set(extra)) - profile['repositories'].keys(), 'unknown repository override')
    repos = {}
    for name, config in profile['repositories'].items():
        root = Path(roots[name]).expanduser().resolve() if roots.get(name) else None
        if root is None or not root.is_dir():
            repos[name] = {'root': str(root) if root else None, 'state': 'missing', 'files': {}}
            continue
        need(git(root, 'rev-parse', '--show-toplevel') == str(root), 'root must be exact Git repository: ' + name)
        files = {}
        paths = config.get('anchors', []) + extra.get(name, [])
        need(isinstance(paths, list) and paths, 'declare actual dependencies: ' + name)
        for relative in sorted(set(paths)):
            path = source(root, relative)
            files[relative] = file_hash(path) if path.is_file() else None
        repos[name] = {'root': str(root), 'state': 'available', 'head': git(root, 'rev-parse', 'HEAD'),
                       'branch': git(root, 'branch', '--show-current'),
                       'tracked_status_sha256': digest(git(root, 'status', '--porcelain', '--untracked-files=no')),
                       'files': files}
    result = {'schema_version': 1, 'project': profile['project'], 'run_id': run_id,
              'profile_sha256': digest(profile), 'repositories': repos,
              'scope': 'declared files only; add transitive production/config/test dependencies before review',
              'release_verified': False}
    result['digest'] = digest(result)
    return result


def verify(profile, snap):
    validate_profile(profile)
    need(snap.get('digest') == digest({k: v for k, v in snap.items() if k != 'digest'}), 'snapshot digest mismatch')
    need(snap.get('schema_version') == 1 and snap.get('project') == profile['project'], 'snapshot project mismatch')
    need(snap.get('profile_sha256') == digest(profile), 'profile changed; capture new snapshot')
    need(set(snap['repositories']) == set(profile['repositories']), 'snapshot repository set mismatch')
    for name, repo in snap['repositories'].items():
        if repo['state'] == 'missing':
            continue
        root = Path(repo['root']).resolve()
        need(git(root, 'rev-parse', '--show-toplevel') == str(root), 'repository moved: ' + name)
        need(git(root, 'rev-parse', 'HEAD') == repo['head'] and
             git(root, 'branch', '--show-current') == repo['branch'], 'Git baseline changed: ' + name)
        for relative, sha in repo['files'].items():
            path = source(root, relative)
            need((file_hash(path) if path.is_file() else None) == sha, 'source changed: ' + name + ':' + relative)


def check(profile, snap, ledger):
    verify(profile, snap)
    need(ledger.get('schema_version') == 1, 'invalid ledger schema')
    for key, value in [('project', profile['project']), ('run_id', snap['run_id']), ('baseline', snap['digest'])]:
        need(ledger.get(key) == value, key + ' mismatch')
    items = ledger.get('assertions')
    need(isinstance(items, list), 'assertions required')
    ids = [a['id'] for a in items]
    targets = {t['id']: t for t in profile['targets']}
    need(len(ids) == len(set(ids)) and set(ids) == set(targets), 'missing/extra/duplicate target assertions')
    counts = Counter()
    for item in items:
        aid, status = item['id'], item.get('status')
        need(status in {'pass', 'fail', 'blocked', 'unreviewed', 'not_applicable'}, aid + ': invalid status')
        need(item.get('method', 'static') == 'static', aid + ': only static claims accepted; use execution receipts separately')
        need(isinstance(item.get('reason'), str) and item['reason'].strip(), aid + ': reason required')
        counts[status] += 1
        if status in {'blocked', 'unreviewed'}:
            continue
        required = targets[aid]['repositories']
        evidence = item.get('evidence', [])
        seen = set()
        for entry in evidence:
            repo_id, relative = entry['repo'], entry['path']
            need(repo_id in snap['repositories'], aid + ': unknown evidence repository')
            repo = snap['repositories'][repo_id]
            need(repo['state'] == 'available' and repo['files'].get(relative), aid + ': source not captured: ' + repo_id + ':' + relative)
            path = source(Path(repo['root']), relative)
            lines = path.read_text(encoding='utf-8').splitlines()
            line, quote = entry.get('line'), entry.get('quote')
            need(type(line) is int and 1 <= line <= len(lines), aid + ': invalid evidence line')
            need(isinstance(quote, str) and quote.strip() and quote in lines[line - 1], aid + ': evidence quote mismatch')
            seen.add(repo_id)
        if status == 'not_applicable':
            need(evidence, aid + ': not_applicable needs source evidence')
            continue
        for field in ('input', 'expected', 'actual', 'rule'):
            need(isinstance(item.get(field), str) and item[field].strip(), aid + ': ' + field + ' required')
        need(set(required) <= seen, aid + ': missing producer/consumer repository evidence')
        edges = []
        for handoff in item.get('handoffs', []):
            a, b = handoff.get('from'), handoff.get('to')
            need(type(a) is int and type(b) is int and 0 <= a < len(evidence) and 0 <= b < len(evidence), aid + ': invalid handoff evidence')
            need(handoff.get('contract') and handoff.get('reason'), aid + ': explain handoff contract')
            edges.append({evidence[a]['repo'], evidence[b]['repo']})
        reached = {required[0]}
        for _ in required:
            for edge in edges:
                if edge & reached:
                    reached |= edge
        need(set(required) <= reached, aid + ': missing handoff chain')
    return {'schema_version': 1, 'project': profile['project'], 'run_id': snap['run_id'],
            'baseline': snap['digest'], 'ledger_sha256': digest(ledger), 'validation': 'passed',
            'counts': dict(sorted(counts.items())), 'automated_assertions': 0,
            'assertions': {item['id']: item['status'] for item in items},
            'release_verified': False, 'meaning': 'declared-source integrity only; static claims still require review; no live acceptance'}


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def binding(manifest, review, root):
    """Optional report binding, mandatory once either input declares cross-repo work."""
    declared = any(a.get('cross_repo_targets') for c in manifest.get('cases', []) for a in c.get('assertions', []))
    left, right = manifest.get('cross_repo'), review.get('cross_repo')
    if left is None and right is None and not declared:
        return None
    need(isinstance(left, dict) and left == right, 'cross_repo binding missing/mismatch')
    documents = {}
    for key in ('profile', 'snapshot', 'ledger'):
        ref = left.get(key)
        need(isinstance(ref, dict) and ref.get('path') and ref.get('sha256'), 'cross_repo ' + key + ' reference required')
        path = Path(ref['path'])
        if not path.is_absolute():
            path = root / path
        need(path.is_file() and file_hash(path) == ref['sha256'], 'cross_repo artifact missing/changed: ' + key)
        documents[key] = load(path)
    result = check(documents['profile'], documents['snapshot'], documents['ledger'])
    need(review['baseline'] == result['baseline'], 'cross_repo report baseline mismatch')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['snapshot', 'verify', 'prepare', 'check'])
    parser.add_argument('--profile', required=True)
    parser.add_argument('--roots', help='local JSON mapping repository id to absolute checkout path')
    parser.add_argument('--dependencies', help='JSON mapping repository id to additional relative file paths')
    parser.add_argument('--run-id')
    parser.add_argument('--snapshot')
    parser.add_argument('--ledger')
    parser.add_argument('--output', required=True, help='new output file; never overwrite an existing artifact')
    args = parser.parse_args()
    try:
        profile = load(args.profile)
        if args.action == 'snapshot':
            need(args.roots, '--roots required')
            result = snapshot(profile, load(args.roots), load(args.dependencies) if args.dependencies else {}, args.run_id)
        else:
            need(args.snapshot, '--snapshot required')
            snap = load(args.snapshot)
            verify(profile, snap)
            if args.action == 'verify':
                result = {'validation': 'passed', 'baseline': snap['digest'], 'release_verified': False}
            elif args.action == 'prepare':
                result = {'schema_version': 1, 'project': profile['project'], 'run_id': snap['run_id'],
                          'baseline': snap['digest'], 'assertions': [
                              {'id': t['id'], 'status': 'unreviewed', 'method': 'static',
                               'reason': 'not reviewed', 'evidence': [], 'handoffs': []} for t in profile['targets']]}
            else:
                need(args.ledger, '--ledger required')
                result = check(profile, snap, load(args.ledger))
        with Path(args.output).open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print(json.dumps({'output': args.output, 'validation': result.get('validation', 'created')}, ensure_ascii=False))
        return 0
    except (ValueError, OSError, TypeError, KeyError) as exc:
        print('CROSS_REPO_VALIDATION_FAILED: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
