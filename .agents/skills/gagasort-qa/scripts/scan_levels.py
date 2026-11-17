#!/usr/bin/env python3
"""Enumerate shipped MessagePack levels and run the production geometry kernel.

Requires msgpack and Pillow. No Unity Editor, asset writes, or game-data changes.
Curve validation is a separate production-kernel stage, never inferred from nodes.
"""
import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path


def save(path, value, compact=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=None if compact else 2), encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def enumerate_levels(repo, out):
    import msgpack
    root = repo / 'GagaSort/Assets/Resources/GagaSort/LevelData'
    hotfix = repo / 'GagaSort/Assets/Art/Hotfix/GagaSort/LevelData'
    records, inputs, files, solver_inputs = [], [], [], []
    seen = set()
    queue = ['default']
    visited = set()
    while queue:
        variant = queue.pop(0)
        if variant in visited:
            continue
        if not variant or Path(variant).name != variant or '.' in variant:
            raise ValueError('Invalid manifest variant: ' + repr(variant))
        visited.add(variant)

        def read(name):
            if Path(name).name != name:
                raise ValueError('Invalid manifest resource name')
            path = root / variant / (name + '.bytes')
            raw = path.read_bytes()
            target = out / 'inputs' / variant / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            mirror = hotfix / variant / path.name
            files.append(dict(path=str(path.relative_to(repo)), sha256=sha(path),
                              snapshot=str(target.relative_to(out)),
                              hotfix_exists=mirror.exists(),
                              hotfix_matches=mirror.exists() and sha(mirror) == sha(path)))
            return msgpack.unpackb(raw, strict_map_key=False)

        manifest = read(f'gagasort_levels_{variant}_manifest')
        if manifest[0] != 2 or manifest[3] != variant:
            raise ValueError('Unsupported or mismatched manifest')
        queue.extend(manifest[4])
        for group in manifest[2]:
            mode, group_id, minimum, maximum, count, name, _, fingerprint, ids = group
            database = read(name)
            levels = database[2].get(mode, {})
            if (set(database[2]) != {mode} or set(levels) != set(ids)
                    or count != len(ids) or minimum != min(ids) or maximum != max(ids)
                    or database[3] != fingerprint):
                raise ValueError(f'Manifest/database mismatch: {name}')
            for number in ids:
                level = levels[number]
                identity = f'{variant}/{mode}/{number}'
                if identity in seen or level[1:3] != [mode, number]:
                    raise ValueError('Duplicate/mismatched identity: ' + identity)
                seen.add(identity)
                solver_inputs.append(dict(level_id=identity, raw_record=level))
                records.append(dict(level_id=identity, number=number, mode=mode,
                                    variant=variant, group=group_id, resource=name,
                                    format_version=level[0]))
                slots = [dict(id=s[0], anchor=s[1], width=s[2], length=s[3],
                              direction=s[4], cp=s[5], slot_type=s[6],
                              fixed_color=s[7], star_target=s[11],
                              cover=s[9], rear=s[14]) for s in level[5]]
                activation = any(s['cover'][0] == 4 for s in slots)
                inputs.append(dict(level_id=identity, number=number, board_size=level[3],
                                   nodes=level[4][2], curves=level[4][3],
                                   elevations=level[4][4], elevation_curves=level[4][5],
                                   loop_mode=level[4][1], format_version=level[0], slots=slots,
                                   has_activation=activation, skip_geometry=activation))
    inventory = dict(schema_version=1, scope='运行时 Resources manifest 的精确关号集合',
                     levels=records, files=files,
                     fingerprint_check='核对 manifest 与分组头中的指纹；未重新计算生产内容指纹')
    save(out / 'level-inventory.json', inventory)
    save(out / 'geometry-input.json', dict(levels=inputs), compact=True)
    save(out / 'solver-input.json', dict(levels=solver_inputs), compact=True)
    return inventory, inputs


def validate_custom_points(level):
    issues = []
    for i, curve in enumerate(level['curves']):
        if curve is None or curve[0] != 1:
            continue
        for name, point in [('in', curve[1]), ('out', curve[2])]:
            if not all(math.isfinite(v) and 0 <= v <= level['board_size'] - 1 for v in point):
                issues.append(dict(rule='custom-control-bounds',
                                   message=f'节点 {i} 的 {name} 控制柄越界或不是有限数', point=point))
    return issues


def draw_level(level, result, target):
    """Plot actual coordinates; unresolved activation coordinates are never plotted at (0,0)."""
    from PIL import Image, ImageDraw, ImageFont
    size = 760
    slots = result.get('resolved_slots', [])
    fonts = ['/System/Library/Fonts/PingFang.ttc', '/System/Library/Fonts/STHeiti Medium.ttc',
             '/System/Library/Fonts/Supplemental/Songti.ttc']
    font_path = next((p for p in fonts if Path(p).exists()), None)
    if not font_path:
        raise RuntimeError('缺少中文绘图字体；不得交付乱码布局图。请为绘图环境安装 CJK 字体。')
    font = ImageFont.truetype(font_path, 17)
    points = list(level['nodes']) + [s['anchor'] for s in slots]
    points.extend(result.get('expanded_path', []))
    for name in ['plot_wall_triangles', 'plot_water_triangles', 'visual_triangles']:
        points.extend(p for triangle in result.get(name, []) for p in triangle)
    for issue in result.get('issues', []) + result.get('visual_issues', []):
        points.extend(issue.get('points', []))
    minimum = [min([-2] + [p[a] - 7 for p in points]) for a in (0, 1)]
    maximum = [max([level['board_size'] + 1] + [p[a] + 7 for p in points]) for a in (0, 1)]
    scale = min((size-100)/(maximum[a]-minimum[a]) for a in (0, 1))
    def xy(p):
        return (50+(p[0]-minimum[0])*scale, size-45-(p[1]-minimum[1])*scale)
    im = Image.new('RGB', (size, size+160), '#f6f8fc')
    d = ImageDraw.Draw(im)
    d.text((25, 12), f"关卡 {level['level_id']} · 真实数据布局 · {result['verdict']}", fill='#183153', font=font)
    lo, hi = xy([0, 0]), xy([level['board_size']-1]*2)
    d.rectangle([lo[0], hi[1], hi[0], lo[1]], outline='#c4cddc', width=2)
    for i, point in enumerate(level['nodes']):
        x, y = xy(point)
        d.ellipse([x-3,y-3,x+3,y+3], fill='#2878bc')
        d.text((x+4,y), str(i), fill='#2878bc')
    path = result.get('expanded_path', [])
    for triangle in result.get('plot_wall_triangles', []):
        d.polygon([xy(p) for p in triangle], fill='#bcc9b0')
    for triangle in result.get('plot_water_triangles', []):
        d.polygon([xy(p) for p in triangle], fill='#79c8e4')
    if len(path) > 1:
        d.line([xy(p) for p in path], fill='#2878bc', width=4)
        if level['loop_mode'] == 0:
            d.line([xy(path[-1]), xy(path[0])], fill='#2878bc', width=4)
    for slot in slots:
        width, length = slot['width'], slot['length']
        if slot['direction'] in (1, 3):
            width, length = length, width
        anchor = slot['anchor']
        a = xy([anchor[0]-(width-1)/2, anchor[1]+(length-1)/2])
        b = xy([anchor[0]+(width-1)/2, anchor[1]-(length-1)/2])
        bad = any(slot['id'] in issue.get('slot_ids', []) for issue in result.get('issues', []))
        d.rectangle([a,b], fill='#ffd9d8' if bad else '#dceedd', outline='#b02b26' if bad else '#398653', width=2)
        d.text(xy(anchor), str(slot['id']), fill='#1f4d2c')
        cp = xy(slot['cp'])
        d.ellipse([cp[0]-3,cp[1]-3,cp[0]+3,cp[1]+3], fill='#e59423')
    for triangle in result.get('visual_triangles', []):
        d.polygon([xy(p) for p in triangle], fill='#f5b99a', outline='#a34816')
    seen_points = set()
    for issue in result.get('issues', []) + result.get('visual_issues', []):
        for point in issue.get('points', []):
            marker = tuple(round(v, 1) for v in point)
            if marker in seen_points:
                continue
            seen_points.add(marker)
            x, y = xy(point)
            d.ellipse([x-4,y-4,x+4,y+4], outline='#c1342b', width=2)
    d.text((25,size+12), '蓝线：真实水道　绿框：泳池　橙点：出入口　棕/红：风险位置', fill='#243b53', font=font)
    d.text((25,size+40), '按实际坐标绘制；激活盒和后池坐标由生产关联算法还原。', fill='#243b53', font=font)
    d.text((25,size+68), '泳池位于棋盘外属于允许的布局；本图不代表关卡已验证有解。', fill='#695c45', font=font)
    for i, issue in enumerate((result.get('issues', []) + result.get('visual_issues', []))[:2]):
        d.text((25,size+96+24*i), issue['message'][:47], fill='#b02b26', font=font)
    target.parent.mkdir(parents=True, exist_ok=True)
    im.save(target)


RULES = {
    'nodes': '棋盘尺寸、节点边界与半格对齐',
    'curves': '真实水道曲线展开、控制柄与曲线越界',
    'relations': '激活盒和前后池引用、派生坐标还原',
    'pools': '泳池尺寸、方向、锚点和彼此重叠',
    'waterway': '泳池压住水道、出入口偏离水道',
}


def finalize(repo, out, inventory, levels):
    geometry = json.loads((out/'geometry-kernel.json').read_text())['levels']
    splines = json.loads((out/'spline-kernel.json').read_text())['levels']
    by_geometry = {x['level_id']: x for x in geometry}
    by_spline = {x['level_id']: x for x in splines}
    expected = {x['level_id'] for x in levels}
    if (len(by_geometry) != len(geometry) or len(by_spline) != len(splines)
            or set(by_geometry) != expected or set(by_spline) != expected):
        raise ValueError('Geometry/spline IDs differ from actual manifest inventory')
    results, anomalies, samples = [], [], []
    for level in levels:
        key = level['level_id']
        g, s = by_geometry[key], by_spline[key]
        issues, unknown = [], []

        def issue(rule, message, slot_ids=None, points=None):
            issues.append(dict(rule=rule, message=message, slot_ids=slot_ids or [], points=points or []))

        if not g['board_size_valid']:
            issue('nodes', '棋盘尺寸不是正数')
        for n in g['nodes']:
            if n.get('invalid') or not n.get('inside_board') or not n.get('half_grid_aligned'):
                issue('nodes', f"节点 {n['index']} 越界、无效或没有对齐半格", points=[n['position']] if 'position' in n else [])
        for i in validate_custom_points(level):
            issue('curves', i['message'], points=[i['point']])
        if not s['expand_ok']:
            issue('curves', '生产水道展开失败：' + s['error'])
            unknown.extend(['relations', 'pools', 'waterway'])
        elif not s['resolve_ok']:
            issue('relations', '生产泳池关联解析失败：' + s['error'])
            unknown.extend(['pools', 'waterway'])
        if s['expand_ok']:
            invalid = [p for p in s['expanded_path'] if not all(math.isfinite(v) and -.5 <= v <= level['board_size']-.5 for v in p)]
            if invalid:
                issue('curves', f'展开水道有 {len(invalid)} 个采样点越出允许边界', points=invalid)
        if s['resolve_ok']:
            if not s['resolved_slots']:
                issue('pools', '关卡没有泳池')
            original = {x['id']: x for x in level['slots']}
            resolved_by_id = {x['id']: x for x in s['resolved_slots']}
            spline_checks = {x['id']: x for x in s['geometry_checks']['slots']}
            for slot in s['resolved_slots']:
                slot_id = slot['id']
                raw = original[slot_id]
                facts = spline_checks[slot_id]
                if slot_id <= 0 or slot['direction'] not in (0, 1, 2, 3):
                    issue('pools', f'泳池 {slot_id} 的编号或方向无效', [slot_id])
                if raw['slot_type'] not in range(6):
                    issue('pools', f'泳池 {slot_id} 的类型无效', [slot_id])
                if slot['rear']:
                    front = resolved_by_id.get(slot['rear'])
                    if front is None or front['id']==slot_id:
                        issue('relations', f'后池 {slot_id} 的前池引用不存在或指向自己', [slot_id])
                    else:
                        if slot['cp'] != front['cp'] or slot['direction'] != front['direction']:
                            issue('relations', f'后池 {slot_id} 与前池 {front["id"]} 的出入口或朝向不一致', [slot_id, front['id']])
                        rear_type_valid = raw['slot_type'] in (0, 1) or (raw['slot_type']==4 and raw['star_target']!=0)
                        if original[front['id']]['slot_type']!=3 or front['rear']!=0 or not rear_type_valid:
                            issue('relations', f'后池 {slot_id} 或前池 {front["id"]} 的类型、绑定层级不合法', [slot_id, front['id']])
                cover = raw['cover']
                sources = cover[3]
                if cover[0]==4:
                    colors = [original[i]['fixed_color'] for i in sources if i in original]
                    if (len(sources) not in (1,2) or cover[2]!=len(sources) or cover[1]!=0
                            or len(set(sources))!=len(sources) or slot_id in sources
                            or any(i not in original or original[i]['slot_type']!=1 for i in sources)
                            or len(set(colors))!=len(sources)):
                        issue('relations', f'激活盒 {slot_id} 的来源引用、类型、颜色或耐久不符合生产规则', [slot_id]+sources)
                elif sources:
                    issue('relations', f'非激活盒 {slot_id} 含激活来源引用', [slot_id]+sources)
                variable = raw['slot_type'] in (3, 4, 5)
                if slot['width'] != 2 or slot['length'] <= 0 or (not variable and slot['length'] != 4):
                    issue('pools', f'泳池 {slot_id} 尺寸不符合类型规则', [slot_id])
                if not all(math.isfinite(v) and 0 <= v <= level['board_size']-1 for v in slot['cp']):
                    issue('waterway', f'泳池 {slot_id} 出入口越出棋盘', [slot_id], [slot['cp']])
                if not facts['nearest_progress_found'] or facts['check_point_distance'] > .15:
                    issue('waterway', f'泳池 {slot_id} 出入口不在水道上（距离 {facts["check_point_distance"]} 格）', [slot_id], [slot['cp']])
                hits = facts.get('covered_path_indices')
                if hits is None:
                    unknown.append('waterway')
                elif hits:
                    issue('waterway', f'泳池 {slot_id} 覆盖水道', [slot_id], [s['expanded_path'][i] for i in hits])
            for slot in g['slots']:
                if slot.get('input_anchor_matches_derived') is not True:
                    issue('pools', f"泳池 {slot['id']} 的锚点不符合出口或前池派生规则", [slot['id']])
            for pair in g['input_overlaps']:
                issue('pools', f"泳池 {pair['first']} 与 {pair['second']} 重叠", [pair['first'], pair['second']])
        for problem in g['issues']:
            issue('pools', '几何输入无效：' + str(problem))
        verdict = '发现问题' if issues else '未定' if unknown else '未见问题'
        filename = 'levels/details/' + key.replace('/', '-') + '.json'
        checks = [dict(rule=k, name=v, verdict='发现问题' if any(i['rule']==k for i in issues) else '未定' if k in unknown else '未见问题') for k, v in RULES.items()]
        record = dict(level_id=key, verdict=verdict, checks=checks, issues=issues,
                      evidence=[filename], scope='布局几何；不含通关有解性、鸭子颜色守恒和完整机关合法性')
        detail = dict(record, input=level, geometry=g, spline=s,
                      whitebox_steps=[
                          f"从本轮运行时清单读取 {key}，原始分组数据见 levels/inputs。",
                          '执行 scan_levels.py；它编译并调用生产 PathBuilder、PoolRelationGeometry 和几何内核。',
                          '核对本文件 checks/issues 与实际坐标；按报告原图查看被标红的对象。'])
        save(out.parent/filename, detail, compact=True)
        results.append(record)
        if issues:
            image = 'levels/images/' + key.replace('/', '-') + '.png'
            draw_level(level, dict(record, **s), out.parent/image)
            anomalies.append(dict(level_id=key, caption='；'.join(i['message'] for i in issues),
                                  image=image, evidence=filename, steps=detail['whitebox_steps']))
    # Representative actual geometry, never disguised as an anomaly.
    representatives = [levels[0], next((x for x in levels if x['has_activation']), levels[0]),
                       max(levels, key=lambda x: len(x['nodes']))]
    for level in {x['level_id']: x for x in representatives}.values():
        key = level['level_id']
        record = next(x for x in results if x['level_id']==key)
        image = 'levels/images/sample-' + key.replace('/', '-') + '.png'
        draw_level(level, dict(record, **by_spline[key]), out.parent/image)
        samples.append(dict(level_id=key, caption=f"实际布局示例：{'含激活盒' if level['has_activation'] else '普通水道'}；{len(level['nodes'])} 个节点、{len(level['slots'])} 个泳池；{record['verdict']}（不代表有解）",
                            image=image, evidence=record['evidence'][0]))
    total = len(levels)
    checked = sum(x['verdict'] in ('未见问题', '发现问题') for x in results)
    save(out/'layout-results.json', dict(schema_version=1, inventory='levels/level-inventory.json', total=total, checked=checked,
        scope='布局几何检查；非完整关卡规则验证或逐关求解', results=results))
    # Solving is a separate pass. Preserve existing real solver evidence if present.
    solver = out/'solvability-results.json'
    if not solver.exists() or not json.loads(solver.read_text()).get('results'):
        save(solver, dict(schema_version=1, inventory='levels/level-inventory.json', total=total, checked=0,
            results=[dict(level_id=x['level_id'], verdict='未检查', checks=['未调用通关求解器；布局正确不能证明有解'],
                          solver=None, budget=None, evidence=['levels/level-inventory.json']) for x in levels]))
    rules = [dict(name=name, status='发现问题' if any(any(i['rule']==rule for i in r['issues']) for r in results) else
                  '检查未完成' if any(any(c['rule']==rule and c['verdict']=='未定' for c in r['checks']) for r in results) else '检查完成未见问题',
                  summary=f"逐关检查 {total} 关；异常 {sum(any(i['rule']==rule for i in r['issues']) for r in results)} 关。") for rule, name in RULES.items()]
    status = '检查未完成' if checked < total else '发现问题' if anomalies else '检查完成未见问题'
    summary = f'已逐关执行 {total} 关布局几何检查，{checked} 关有明确结论，{len(anomalies)} 关发现布局问题；含 {sum(x["has_activation"] for x in levels)} 个激活盒关卡。未执行逐关求解和完整机关规则验证。'
    report = dict(inventory_file='levels/level-inventory.json',
        layout=dict(status=status, summary=summary, total=total, checked=checked,
                    run_ids=['RUN-LEVEL-LAYOUT'], evidence=['levels/layout-results.json', 'levels/run-metadata.json'],
                    result_file='levels/layout-results.json', rule_results=rules), anomalies=anomalies, samples=samples)
    save(out/'report-fragment.json', report)
    source_paths = [repo/'GagaSort/Assets/Scripts/GamePlay/GagaSort/Runtime/Level/GagaSortLevelValidator.cs',
                    repo/'GagaSort/Assets/Scripts/GamePlay/GagaSort/Runtime/Logic/GagaSortMechanismRules.cs',
                    repo/'GagaSort/Assets/Resources/GagaSort/Config/GagaSortGameConfig.asset']
    save(out/'run-metadata.json', dict(timestamp=datetime.now().astimezone().isoformat(),
        head=subprocess.check_output(['git','rev-parse','HEAD'], cwd=repo, text=True).strip(),
        command=sys.argv, rules_source=[dict(path=str(p.relative_to(repo)),sha256=sha(p)) for p in source_paths],
        total=total, checked=checked, anomaly_levels=len(anomalies), summary=summary,
        production_full_validator_executed=False, solver_executed=False))
    print(summary, flush=True)


def ensure_dependencies(dependency_path):
    if dependency_path:
        sys.path.insert(0, str(dependency_path))
    try:
        import msgpack
        from PIL import Image
    except ImportError:
        path = Path(tempfile.gettempdir())/'gagasort-qa-layout-deps'
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--target', str(path),
                        'msgpack==1.2.4', 'Pillow==12.1.1'], check=True)
        sys.path.insert(0, str(path))


def execute_stage(command, log):
    """Keep the actual command output even when a build or probe fails."""
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('w') as stream:
        stream.write('Command: ' + repr(command) + '\n')
        stream.flush()
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)
        stream.write('\nExit code: ' + str(result.returncode) + '\n')
    if result.returncode:
        raise RuntimeError(f'Stage failed ({result.returncode}); evidence: {log}')


def copy_build_evidence(cache, destination):
    destination.mkdir(parents=True, exist_ok=True)
    for file in cache.iterdir():
        if file.is_file() and (file.suffix in {'.log', '.rsp', '.diff'} or file.name == 'manifest.json'):
            shutil.copy2(file, destination/file.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dependency-path', type=Path)
    parser.add_argument('--enumerate-only', action='store_true')
    parser.add_argument('--solver-time-ms', type=int, default=200)
    args = parser.parse_args()
    ensure_dependencies(args.dependency_path)
    repo, out = args.repo.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    inventory, levels = enumerate_levels(repo, out)
    print(f'枚举 {len(levels)} 关；含激活盒 {sum(x["has_activation"] for x in levels)} 关。', flush=True)
    if args.enumerate_only:
        return
    spline = Path(__file__).with_name('build_level_splines.py')
    import re
    config = (repo/'GagaSort/Assets/Resources/GagaSort/Config/GagaSortGameConfig.asset').read_text()
    radius = re.search(r'^\s*RightAngleCornerRadiusCells:\s*([\d.]+)\s*$', config, re.M)
    if not radius:
        raise ValueError('Cannot read production RightAngleCornerRadiusCells')
    cache = Path(tempfile.gettempdir())/'gagasort-qa-spline-cache'
    # SDK packages and compiler binaries are disposable caches, not report attachments.
    subprocess.run([sys.executable, str(spline), '--repo', str(repo), '--input', str(out/'geometry-input.json'),
                    '--output', str(out/'spline-kernel.json'), '--build-dir', str(cache),
                    '--radius', radius[1]], check=True)
    evidence = out/'spline-kernel-build'
    evidence.mkdir(exist_ok=True)
    for file in cache.iterdir():
        if file.suffix in {'.log', '.rsp', '.diff'} or file.name in {'manifest.json', 'CurveUtility.Headless.cs'}:
            shutil.copy2(file, evidence/file.name)
    resolved = json.loads((out/'spline-kernel.json').read_text())['levels']
    by_id = {x['level_id']: x for x in resolved}
    resolved_inputs = []
    for level in levels:
        s = by_id[level['level_id']]
        resolved_inputs.append(dict(level, slots=s.get('resolved_slots', level['slots']), skip_geometry=not s['resolve_ok']))
    save(out/'resolved-geometry-input.json', dict(levels=resolved_inputs))
    helper = Path(__file__).with_name('build_level_geometry.py')
    subprocess.run([sys.executable, str(helper), '--repo', str(repo), '--input', str(out/'resolved-geometry-input.json'),
                    '--output', str(out/'geometry-kernel.json'),
                    '--evidence', str(out/'geometry-kernel-build')], check=True)
    finalize(repo, out, inventory, levels)
    # A full scan always executes these stages. Source inspection of a solver
    # or a zero in the basic geometry stage cannot substitute for either.
    solver_cache = Path(tempfile.gettempdir())/'gagasort-qa-solver-cache'
    solver_helper = Path(__file__).with_name('build_level_solver.py')
    print(f'执行正式 Validator / 无道具求解 / 独立回放：{len(levels)} 关，每关 {args.solver_time_ms}ms 搜索预算。', flush=True)
    try:
        execute_stage([sys.executable, str(solver_helper), '--repo', str(repo), '--input', str(out/'solver-input.json'),
            '--output', str(out/'solver-kernel.json'), '--build-dir', str(solver_cache),
            '--kernel-dir', str(cache), '--time-ms', str(args.solver_time_ms)], out/'solver-stage.log')
    finally:
        if solver_cache.exists():
            copy_build_evidence(solver_cache, out/'solver-kernel-build')
    visual_cache = Path(tempfile.gettempdir())/'gagasort-qa-visual-cache'
    print('执行真实岸壁与水面网格风险检查：动态回退和正式配方分别留证。', flush=True)
    try:
        execute_stage([sys.executable, str(Path(__file__).with_name('build_level_visuals.py')),
            '--repo', str(repo), '--input', str(out/'geometry-input.json'),
            '--output', str(out/'visual-results.json'), '--build-dir', str(visual_cache),
            '--spline-build', str(cache), '--radius', radius[1]], out/'visual-stage.log')
    finally:
        if visual_cache.exists():
            copy_build_evidence(visual_cache, out/'visual-kernel-build')
    from summarize_level_checks import complete
    complete(out, levels, inventory, draw_level)


if __name__ == '__main__':
    main()
