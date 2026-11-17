#!/usr/bin/env python3
"""Publish only browser-verified portable data and the fixed offline viewer."""
import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from export_portable_report import SKILL, build_viewer
from portable_delivery import FORMAT, sha256, snapshot, verify_receipt

RUN_TIMESTAMP = re.compile(r'^full-audit-(\d{8}-\d{6})$')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def verified_source(run_dir):
    delivery = read(run_dir / 'delivery-check.json')
    profile = read(SKILL / 'assets/delivery-profile.json')
    if not delivery.get('report_ready') or delivery.get('format') != FORMAT:
        raise ValueError('本轮便携报告尚未通过交付校验，请先执行 finalize_report.py')
    manifest_path = run_dir / 'portable-manifest.json'
    receipt_path = run_dir / 'portable-interaction-check.json'
    if (delivery.get('portable_manifest_sha256') != sha256(manifest_path)
            or delivery.get('interaction_receipt_sha256') != sha256(receipt_path)):
        raise ValueError('交付清单或交互回执已变化')
    manifest, receipt = read(manifest_path), read(receipt_path)
    if manifest.get('workflow_version') != profile['workflow_version']:
        raise ValueError('工作流版本已变化，需重新校验后发布')
    stage = (run_dir / manifest['directory']).resolve()
    if stage == run_dir or not stage.is_relative_to(run_dir):
        raise ValueError('便携交付路径越界')
    viewer, bundle = stage / '查看报告.html', stage / 'batch'
    verify_receipt(receipt, viewer, bundle)
    if manifest.get('files') != snapshot(viewer, bundle):
        raise ValueError('便携产物与生成清单不一致')
    if manifest.get('report_data_sha256') != sha256(run_dir / 'report-data.json'):
        raise ValueError('报告数据已变化，需重新校验')
    if viewer.read_bytes() != build_viewer().encode('utf-8'):
        raise ValueError('查看器与当前固化版本不一致')
    return viewer, bundle, manifest['files']


def publish(run_dir: Path, output_dir: Path) -> dict:
    run_dir, output_dir = run_dir.resolve(), output_dir.resolve()
    viewer, bundle, expected = verified_source(run_dir)
    if not re.fullmatch(r'\d{8}-\d{6}', output_dir.name):
        raise ValueError('交付批次目录必须使用 YYYYMMDD-HHMMSS')
    if output_dir.exists():
        raise ValueError('目标批次已存在，拒绝修改历史文件')
    target_viewer = output_dir.parent / '查看报告.html'
    if target_viewer.exists() and (target_viewer.is_symlink() or target_viewer.read_bytes() != viewer.read_bytes()):
        raise ValueError('固定查看器版本不同，拒绝覆盖；请先独立验收并明确升级')
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.publish-', dir=output_dir.parent))
    try:
        copied = temporary / 'batch'
        shutil.copytree(bundle, copied)
        if snapshot(viewer, copied) != expected:
            raise ValueError('复制后的数据与已验证产物不一致')
        # Verify once more before exposing files. Publication does not rerender data.
        verified_source(run_dir)
        if not target_viewer.exists():
            with target_viewer.open('xb') as stream:
                stream.write(viewer.read_bytes())
        if output_dir.exists():
            raise ValueError('目标批次在发布期间出现，拒绝覆盖')
        copied.rename(output_dir)
    finally:
        shutil.rmtree(temporary)
    return dict(run_dir=str(run_dir), output_dir=str(output_dir), viewer=str(target_viewer),
                format=FORMAT, files=expected)


def timestamped_output_dir(run_dir: Path, output_root: Path, timestamp: str | None = None) -> Path:
    match = RUN_TIMESTAMP.fullmatch(run_dir.resolve().name)
    value = timestamp or (match.group(1) if match else None)
    if not value or not re.fullmatch(r'\d{8}-\d{6}', value):
        raise ValueError('无法从本轮目录提取时间戳，请传入 --timestamp YYYYMMDD-HHMMSS')
    return output_root.resolve() / value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True, help='已通过 finalize_report.py 校验的本轮目录')
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument('--output-dir', type=Path, help='新的时间戳批次目录；固定查看器放其上一级')
    output.add_argument('--output-root', type=Path, help='质量报告根目录')
    parser.add_argument('--timestamp', help='显式指定 YYYYMMDD-HHMMSS')
    args = parser.parse_args()
    output_dir = args.output_dir or timestamped_output_dir(args.run_dir, args.output_root, args.timestamp)
    print(json.dumps(publish(args.run_dir, output_dir), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
