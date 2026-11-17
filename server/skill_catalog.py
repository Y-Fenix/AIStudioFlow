"""Pinned, offline defaults. This module never downloads or executes upstream code."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def github_default(key):
    catalog = json.loads((ROOT / 'server/skills/github-defaults.json').read_text(encoding='utf-8'))
    entry = catalog['nodes'][key]
    path = ROOT / entry['path']
    content = path.read_text(encoding='utf-8')
    return {'name':entry['name'], 'content':content, 'source_kind':'bundled',
            'source_path':str(path.resolve()), 'upstream_sources':entry['sources'],
            'sha256':hashlib.sha256(content.encode()).hexdigest()}
