#!/usr/bin/env python3
"""Bind portable report publication to the exact browser-checked files."""
import hashlib
import json
from pathlib import Path

FORMAT = 'gagasort-report-v1'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(viewer, bundle):
    viewer, bundle = Path(viewer), Path(bundle)
    if viewer.is_symlink() or not viewer.is_file() or not bundle.is_dir() or bundle.is_symlink():
        raise ValueError('查看器或数据目录缺失，或包含软链接')
    if {p.name for p in bundle.iterdir()} != {'report.md', 'bugs.csv', 'images'}:
        raise ValueError('批次目录只能包含 report.md、bugs.csv、images/')
    if not (bundle / 'images').is_dir():
        raise ValueError('images 必须为目录，即使本轮没有图片')
    files = {'viewer': sha256(viewer)}
    for path in sorted(bundle.rglob('*')):
        if path.is_symlink():
            raise ValueError('报告内不允许软链接')
        if path.is_file():
            files['bundle/' + path.relative_to(bundle).as_posix()] = sha256(path)
    if not all((bundle / p).is_file() for p in ('report.md', 'bugs.csv')):
        raise ValueError('缺 MD 或 CSV')
    return files


def verify_receipt(receipt, viewer, bundle):
    if receipt.get('status') != 'passed' or not receipt.get('checks') or receipt.get('format') != FORMAT:
        raise ValueError('缺少便携报告真实交互通过回执')
    if receipt.get('files') != snapshot(viewer, bundle):
        raise ValueError('报告文件与浏览器交互回执不一致')
