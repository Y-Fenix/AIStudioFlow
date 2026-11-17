"""Frozen testing inputs; no database, Git, tool execution or permission grants."""
import hashlib
import json
from pathlib import Path

QA_REPOSITORIES = frozenset(('client', 'android', 'ios', 'sdkserver', 'gameserver'))
QA_SKILLS = ('test-case', 'test-codetest', 'test-server-sdk', 'gagasort-qa')
QA_CHECKS = frozenset(('source_review', 'syntax', 'whitebox'))
QA_EXCLUDED = frozenset(('.git', '__pycache__', '.DS_Store'))
QA_PACKAGE_LIMIT = 32 * 1024 * 1024


def QA_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def QA_package(folder):
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError('missing or symlink skill package: ' + str(folder))
    files = {}
    total = 0
    pending = [folder]
    while pending:
        parent = pending.pop()
        for path in sorted(parent.iterdir()):
            if path.name in QA_EXCLUDED:
                continue
            if path.is_symlink():
                raise ValueError('symlink skill dependency: ' + str(path))
            if path.is_dir():
                pending.append(path)
                continue
            if not path.is_file():
                raise ValueError('unsupported skill dependency: ' + str(path))
            before = path.stat()
            total += before.st_size
            if total > QA_PACKAGE_LIMIT or len(files) >= 10000:
                raise ValueError('skill package exceeds limit')
            with path.open('rb') as stream:
                content = stream.read(QA_PACKAGE_LIMIT + 1)
            after = path.stat()
            if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError('skill dependency changed during read')
            if len(content) != before.st_size:
                raise ValueError('skill dependency changed during read')
            files[path.relative_to(folder).as_posix()] = hashlib.sha256(content).hexdigest()
    if 'SKILL.md' not in files:
        raise ValueError('missing SKILL.md: ' + str(folder))
    return {'root': str(folder), 'files': files, 'sha256': QA_digest(files)}


def QA_freeze_profile(repositories, skill_root, *, allowed_checks=('source_review',)):
    if not isinstance(repositories, dict) or set(repositories) != QA_REPOSITORIES:
        raise ValueError('profile requires client and four SDK/server repository IDs')
    if not isinstance(allowed_checks, (list, tuple)) or not allowed_checks or any(
            check not in QA_CHECKS for check in allowed_checks):
        raise ValueError('unsupported checks')
    roots = {}
    for name, raw in repositories.items():
        if not isinstance(raw, str) or not Path(raw).is_absolute():
            raise ValueError('repository path must be absolute')
        path = Path(raw)
        # System temporary roots can contain compatibility symlinks (for
        # example /var on macOS).  Rejecting those makes valid repositories
        # unusable; the security boundary is the requested root itself.
        if path.is_symlink():
            raise ValueError('symlink repository root')
        roots[name] = path.resolve()
    for name, path in roots.items():
        if any(name != other and (path.is_relative_to(candidate) or
               candidate.is_relative_to(path)) for other, candidate in roots.items()):
            raise ValueError('repository roots overlap')
    skill_root = Path(skill_root)
    if not skill_root.is_absolute() or skill_root.is_symlink():
        raise ValueError('skill root must be absolute without symlink ancestors')
    payload = {
        'schema_version': 1,
        'repositories': {name: {'root': str(path), 'available': path.is_dir()}
                         for name, path in sorted(roots.items())},
        'skills': {name: QA_package(skill_root / name) for name in QA_SKILLS},
        'allowed_checks': sorted(set(allowed_checks)),
        'external_publication': False,
        'source_baseline': 'not_captured',
    }
    payload['sha256'] = QA_digest(payload)
    return payload


def QA_verify_profile(frozen):
    """Detect input drift only; caller must independently recheck authorization."""
    gaps = []
    try:
        body = {key: value for key, value in frozen.items() if key != 'sha256'}
        if QA_digest(body) != frozen['sha256']:
            return {'valid': False, 'gaps': ['profile_changed']}
        if frozen['schema_version'] != 1 or frozen['external_publication'] is not False:
            return {'valid': False, 'gaps': ['unsupported_profile']}
        if set(frozen['repositories']) != QA_REPOSITORIES or set(frozen['skills']) != set(QA_SKILLS):
            return {'valid': False, 'gaps': ['invalid_profile_scope']}
        checks = frozen['allowed_checks']
        if not checks or any(check not in QA_CHECKS for check in checks):
            return {'valid': False, 'gaps': ['unsupported_checks']}
        roots = {name: item['root'] for name, item in frozen['repositories'].items()}
        skill_parents = {str(Path(item['root']).parent) for item in frozen['skills'].values()}
        if len(skill_parents) != 1:
            return {'valid': False, 'gaps': ['invalid_skill_roots']}
        current = QA_freeze_profile(roots, skill_parents.pop(), allowed_checks=checks)
        for name, item in current['repositories'].items():
            if not item['available']:
                gaps.append('repository_unavailable:' + name)
            elif item != frozen['repositories'][name]:
                gaps.append('repository_changed:' + name)
        for name in QA_SKILLS:
            if current['skills'][name] != frozen['skills'][name]:
                gaps.append('skill_package_changed:' + name)
    except (KeyError, TypeError, ValueError, OSError) as error:
        gaps.append('profile_verification_failed:' + type(error).__name__)
    return {'valid': not gaps, 'gaps': gaps}
