#!/usr/bin/env python3
"""Export independent MD/CSV/images report bundles and a reusable offline viewer."""
import argparse
import base64
import copy
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile

SKILL = Path(__file__).resolve().parents[1]
FENCE = 'gagasort-report-v1'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def payload_from_html(path):
    text = path.read_text(encoding='utf-8')
    marker = '<script id="payload" type="application/json">'
    if text.count(marker) != 1:
        raise ValueError('不是已固化的 GagaSort 报告，缺少唯一 payload')
    start = text.index(marker) + len(marker)
    return json.loads(text[start:text.index('</script>', start)])


def safe_path(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or '..' in path.parts or '\\' in value or ':' in value:
        raise ValueError('不安全的报告相对路径：' + value)
    return path


def csv_rows(raw, headers, ids):
    rows = list(csv.reader(io.StringIO(raw.decode('utf-8-sig'), newline=''), strict=True))
    if not rows or rows[0] != headers or len(set(headers)) != len(headers):
        raise ValueError('CSV 表头与报告不一致或存在重复列')
    values = rows[1:]
    if len(values) != len(ids) or len(set(ids)) != len(ids):
        raise ValueError('CSV 行数或 Bug 编号不一致')
    column = headers.index('缺陷描述')
    for row, bug_id in zip(values, ids):
        if len(row) != len(headers) or bug_id not in row[column].split('\n', 1)[0]:
            raise ValueError('CSV 列数或 Bug 编号顺序不一致：' + bug_id)
    return values


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def evidence_notes(view, asset_reader):
    """Keep referenced source windows, never copy entire execution directories."""
    anchors = {}
    for node in walk(view):
        if isinstance(node.get('path'), str) and type(node.get('line')) is int:
            source = node['path']
            key = '/'.join(source.split('/')[3:]) if source.startswith('QA/') else 'sources/' + source + '.txt'
            anchors.setdefault(key, set()).add(node['line'])
    notes = {}
    for path, lines in sorted(anchors.items()):
        asset = asset_reader(path)
        if not asset or 'text' not in asset:
            continue
        original = asset['text'].splitlines()
        selected = sorted({i for line in lines for i in range(max(1, line-5), min(len(original), line+8)+1)})
        excerpt = '\n'.join(f'{i:>6} | {original[i-1]}' for i in selected)
        raw = excerpt.encode('utf-8')
        notes[path] = {'text': excerpt, 'kind': 'excerpt', 'sha256': digest(raw),
                       'source_sha256': asset.get('sha256', ''), 'bytes': len(raw)}
    paths = {r.get('evidence') for r in view.get('runs', {}).values()}
    paths.update(i.get('log') for i in view['issues'])
    for path in sorted(p for p in paths if isinstance(p, str) and p not in notes):
        asset = asset_reader(path)
        if not asset or 'text' not in asset:
            continue
        text = asset['text']
        shortened = len(text) > 16000
        if shortened:
            text = text[:8000] + '\n\n[中间内容省略；完整日志保留在执行目录]\n\n' + text[-8000:]
        raw = text.encode('utf-8')
        notes[path] = {'text': text, 'kind': 'excerpt' if shortened else 'log',
                       'sha256': digest(raw), 'source_sha256': asset.get('sha256', ''), 'bytes': len(raw)}
    return notes


def adapted_template():
    raw = (SKILL / 'assets/report-template.html').read_bytes()
    profile = json.loads((SKILL / 'assets/delivery-profile.json').read_text(encoding='utf-8'))
    if digest(raw) != profile['template_sha256']:
        raise ValueError('原报告模板指纹不一致，拒绝生成未复核的查看器')
    source = raw.decode('utf-8')
    def replace_function(name, body):
        nonlocal source
        pattern = rf'^function {name}\([^\n]*\n'
        source, count = re.subn(pattern, lambda _: body + '\n', source, flags=re.M)
        if count != 1:
            raise ValueError('旧模板接口已变化，请更新便携适配及回归：' + name)
    replace_function('fileLink', '''function fileLink(path,label='查看关键证据'){return path?D.assets[path]?`<a href="#" class="evidence-link" data-file="${E(path)}">${E(label)} ↗</a>`:`<span class="tiny">完整执行文件保留在原执行目录；本报告提供结论与必要摘录。</span>`:''}''')
    replace_function('traceLinks', '''function traceLinks(trace){return (trace||[]).map(x=>{const path=x.path.startsWith('QA/')?x.path.split('/').slice(3).join('/'):'sources/'+x.path+'.txt';return `<p class="tiny">${E(x.note)}</p>`+(D.assets[path]?`<a class="code-ref" href="#" data-file="${E(path)}">${E(x.path)}:${E(x.line)} · 关键摘录 ↗</a>`:`<span class="code-ref">${E(x.path)}:${E(x.line)}</span>`)}).join('')}''')
    replace_function('showEvidence', '''function showEvidence(path,line){const a=D.assets[path];$('evidence-title').textContent=path;$('evidence-body').textContent=a?.text||'该执行文件不在分发包内；请查看问题结论与推导。';$('evidence-hash').textContent=a?`${a.kind==='excerpt'?'关键摘录（非完整原文件）':'日志'} · 摘录 SHA256：${a.sha256} · 原文件 SHA256：${a.source_sha256||'未记录'}`:'';$('download-evidence').hidden=true;$('evidence').showModal();$('evidence-body').scrollTop=0}''')
    old = 'src="data:${D.assets[a.image].mime};base64,${D.assets[a.image].base64}"'
    if source.count(old) != 1:
        raise ValueError('旧模板图片接口已变化')
    source = source.replace(old, 'loading="lazy" src="${E(D.assets[a.image].url)}"')
    source = source.replace('（快照未内嵌）', '（源码位置）')
    # file:// and opaque Blob documents cannot reliably navigate URL fragments.
    # Keep the same report routes in memory; no local-resource navigation is needed.
    source = source.replace("'use strict';", "'use strict';let portableHash='';")
    source = source.replace('location.hash', 'portableHash')
    source = source.replace("history.replaceState(null,'','#'+returnHash)", "portableHash='#'+returnHash")
    source = source.replace("portableHash='module-'+catKey(category)+'-'+fb.dataset.filter;return", "portableHash='#module-'+catKey(category)+'-'+fb.dataset.filter;route();return")
    navigation = "document.addEventListener('click',event=>{const link=event.target.closest('a[href^=\"#\"]');if(!link||link.dataset.file)return;event.preventDefault();const hash=link.getAttribute('href');if(hash.length>1){portableHash=hash;route()}});"
    source = source.replace("window.addEventListener('hashchange',route);route();", navigation + 'route();')
    source = source.replace("const proof=i.static_proof;", "const original=i.static_proof,full=bugRows.find(r=>r.id===i.id)?.detail;const proof={...original,steps:full?.steps?.length?full.steps:original.steps};")
    # Each external action requires a deliberate click and live bridge authentication.
    # Never use authorization flags or credentials from a historical report.
    source = source.replace('const writeAuthorized=D.feishu_authorized===true;', 'const writeAuthorized=true;')
    csp = "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src blob: data:; connect-src http://127.0.0.1:17321; base-uri 'none'; form-action 'none'\">"
    return source.replace('<head>', '<head>\n' + csp)


def build_viewer():
    raw = (SKILL / 'assets/portable-viewer.html').read_bytes()
    profile = json.loads((SKILL / 'assets/delivery-profile.json').read_text(encoding='utf-8'))
    if digest(raw) != profile['portable_viewer_sha256']:
        raise ValueError('便携查看器指纹不一致，拒绝未复核改版')
    shell = raw.decode('utf-8')
    template = json.dumps(adapted_template(), ensure_ascii=False).replace('<', '\\u003c')
    if shell.count('__REPORT_TEMPLATE__') != 1:
        raise ValueError('便携查看器缺少唯一模板插槽')
    return shell.replace('__REPORT_TEMPLATE__', template)


def markdown_report(package):
    view = package['view']
    lines = ['# GagaSort 质量报告', '', '> ' + package['notice'], '',
             f"- 批次：{view['baseline']['run_id']}", f"- 源码基线：{view['baseline']['head']}",
             f"- 功能：{len(view['features'])} 项；已确认 Bug：{len(view['bug_register']['rows'])} 条；图片：{len(package['images'])} 张。",
             '', '## 结论', '', view['presentation']['conclusion'], '', '## 检查范围与结果', '',
             '| 分类 | 功能 | 检查内容 | 结果 |', '| --- | --- | --- | --- |']
    cell = lambda s: str(s).replace('|', '\\|').replace('\n', ' ')
    for f in view['features']:
        lines.append('| ' + ' | '.join(cell(f.get(k, '')) for k in ('category_plain', 'name_plain', 'check_plain', 'outcome')) + ' |')
    lines += ['', '## Bug 内容', '', f"完整 {len(view['bug_register']['headers'])} 列、触发条件、复现步骤、实际表现与归因保存在同目录 bugs.csv；空列保留。",
              '下方机器数据包含功能分支、关键证据摘录和关卡明细。原始探针/源码全文/完整日志保留在执行目录；这些文件不影响离线渲染。',
              '', '## 关卡图片与解释', '']
    for group in ('risks', 'anomalies', 'samples'):
        for item in view['level_audit'].get(group, []):
            lines += [f"### {item['level_id']} · {item['caption']}", '', f"![{item['level_id']}]({item['image']})", '']
            lines += [f'{i}. {s}' for i, s in enumerate(item.get('steps', []), 1)]
            lines.append('')
    lines += ['## 查看器数据（格式 v1）', '', '此区块供固定 HTML 读取；可由 Codex 读取，手改后须重新导出以更新校验。', '',
              '```' + FENCE, json.dumps(package, ensure_ascii=False, indent=2).replace('`', '\\u0060'), '```', '']
    return '\n'.join(lines)


def export_bundle(view, csv_raw, asset_reader, output, notice):
    output = output.resolve()
    if output.exists():
        raise ValueError('目标目录已存在，拒绝修改历史文件：' + str(output))
    view = copy.deepcopy({k: v for k, v in view.items() if k != 'assets'})
    rows = view['bug_register']['rows']
    ids = [r['id'] for r in rows]
    csv_rows(csv_raw, view['bug_register']['headers'], ids)
    if set(ids) != {i['id'] for i in view['issues'] if i['confirmed']}:
        raise ValueError('已确认问题与 CSV 列表不一致')
    notes = evidence_notes(view, asset_reader)
    images, binaries = [], {}
    for group in ('risks', 'anomalies', 'samples'):
        for item in view['level_audit'].get(group, []):
            original = str(safe_path(item['image']))
            asset = asset_reader(original)
            if not asset or not asset.get('base64') or asset.get('mime') not in {'image/png', 'image/jpeg', 'image/webp'}:
                raise ValueError('缺少有效的关卡图片：' + original)
            raw = base64.b64decode(asset['base64'], validate=True)
            extension = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}[asset['mime']]
            path = 'images/' + digest(raw)[:20] + extension
            item['image'] = path
            if path not in binaries:
                binaries[path] = raw
                images.append({'path': path, 'sha256': digest(raw), 'bytes': len(raw), 'mime': asset['mime']})
    for row in rows:
        row.pop('fields', None)  # CSV is the only source for ticket field values.
    view['bug_register'].pop('csv', None)
    view['feishu_authorized'] = False
    package = {'format': FENCE, 'notice': notice, 'csv': {'path': 'bugs.csv', 'sha256': digest(csv_raw),
               'bytes': len(csv_raw), 'headers': view['bug_register']['headers'], 'ids': ids},
               'images': images, 'evidence_notes': notes, 'view': view}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.portable-', dir=output.parent))
    try:
        (temporary / 'images').mkdir()
        (temporary / 'bugs.csv').write_bytes(csv_raw)
        (temporary / 'report.md').write_text(markdown_report(package), encoding='utf-8')
        for path, raw in binaries.items():
            (temporary / path).write_bytes(raw)
        temporary.rename(output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {'output': str(output), 'bugs': len(rows), 'features': len(view['features']),
            'images': len(images), 'evidence_notes': len(notes),
            'bytes': sum(p.stat().st_size for p in output.rglob('*') if p.is_file())}


def load_run(run_dir, data=None):
    from render_report import validate, prepare_view
    if data is None:
        data = json.loads((run_dir / 'report-data.json').read_text(encoding='utf-8'))
    validate(data, run_dir)
    view = prepare_view(data)
    level = view['level_audit']
    if level.get('visual'):
        result = json.loads((run_dir / level['visual']['result_file']).read_text(encoding='utf-8'))
        by_id = {str(r['level_id']): r for r in result['results']}
        level['risks'] = [dict(r, risk_types=[k for k in ('wall', 'water') if by_id[str(r['level_id'])].get(k+'_risk')]) for r in level.get('risks', [])]
    def read_asset(path):
        file = run_dir / str(safe_path(path))
        if not file.is_file():
            return None
        raw = file.read_bytes()
        base = {'sha256': digest(raw)}
        mime = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}.get(file.suffix.lower())
        return dict(base, base64=base64.b64encode(raw).decode(), mime=mime) if mime else dict(base, text=raw.decode('utf-8', errors='replace'))
    # register_csv already includes the BOM; utf-8-sig would prepend a second one.
    return view, view['bug_register']['csv'].encode('utf-8'), read_asset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--source-html', type=Path, help='仅转换已生成报告，保留旧检查基线')
    source.add_argument('--run-dir', type=Path, help='读取已校验的本轮数据，不先生成巨型 HTML')
    parser.add_argument('--csv', type=Path, help='转换时读取原始 CSV，保留所有列及字节')
    parser.add_argument('--output-dir', type=Path, required=True, help='必须为不存在的新时间戳目录')
    parser.add_argument('--viewer-output', type=Path, required=True, help='固定查看器的新路径；存在则只接受完全相同的版本')
    args = parser.parse_args()
    viewer = build_viewer().encode('utf-8')
    if args.viewer_output.exists() and args.viewer_output.read_bytes() != viewer:
        raise ValueError('查看器已存在且版本不同，请使用新路径验收，拒绝覆盖')
    if args.source_html:
        original = payload_from_html(args.source_html)
        assets = original.pop('assets')
        raw = args.csv.read_bytes() if args.csv else original['bug_register']['csv'].encode('utf-8')
        reader = assets.get
        notice = '历史批次格式转换，仅用于便携报告验收；未重新巡检，Bug 数量及源码基线沿用原批次。'
    else:
        original, raw, reader = load_run(args.run_dir.resolve())
        notice = '本报告来自所列批次的检查数据；完整度与限制以原检查结论为准，导出不执行产品测试。'
    result = export_bundle(original, raw, reader, args.output_dir, notice)
    args.viewer_output.parent.mkdir(parents=True, exist_ok=True)
    if not args.viewer_output.exists():
        with args.viewer_output.open('xb') as stream:
            stream.write(viewer)
    print(json.dumps(dict(result, viewer=str(args.viewer_output.resolve())), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
