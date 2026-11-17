#!/usr/bin/env python3
"""Combine real level-stage artifacts. Never infer a pass from missing output."""
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')))


def complete(out, levels, inventory, draw_level):
    fragment = read(out / 'report-fragment.json')
    solver = read(out / 'solver-kernel.json')
    visual = read(out / 'visual-results.json')
    expected = {x['level_id'] for x in levels}
    def indexed(rows, name):
        result = {str(x['level_id']): x for x in rows}
        if len(result) != len(rows) or set(result) != expected:
            raise ValueError(name + ' IDs do not exactly match inventory')
        return result
    by_solver = indexed(solver['levels'], 'solver')
    by_visual = indexed(visual['levels'], 'visual')
    layout = indexed(read(out / 'layout-results.json')['results'], 'layout')
    splines = indexed(read(out / 'spline-kernel.json')['levels'], 'spline')
    solvability, visuals, risks, table = [], [], [], []
    invalid, validation_unknown = [], []
    for level in levels:
        key = level['level_id']
        s, v = by_solver[key], by_visual[key]
        evidence = 'levels/details/' + key.replace('/', '-') + '.json'
        # A solver label alone is insufficient: every successful solution must
        # reach the production completion flag in a fresh runtime replay.
        replay = s.get('replay') or {}
        validation = s.get('validation', {})
        valid = validation.get('valid')
        solved = (valid is True and s['status'] == 'Solvable' and replay.get('has_completed') is True
                  and replay.get('independent_runtime') is True)
        verdict = ('未见问题' if solved else '发现问题' if valid is False or s['status'] in {'Unsolvable', 'Invalid'} else '未定')
        if valid is False or s['status'] == 'Invalid':
            invalid.append(key)
        elif valid is not True:
            validation_unknown.append(key)
        solvability.append(dict(level_id=key, verdict=verdict, checks=[
            dict(name='正式无道具求解与全新运行时回放', verdict=verdict, status=s['status'], reason=s.get('reason', ''))],
            solver='GagaSortSolvabilitySolver + GagaSortDifficultyEvaluator + GagaSortLogicRuntime', budget=solver.get('budget'),
            evidence=[evidence], status=s['status'], replay_completed=solved))
        sources = v.get('sources', [])
        errors = [x.get('error') for x in sources if x.get('error')]
        errors.extend('配方指纹不匹配，未检查其网格' for x in sources if x.get('status') == 'fingerprint_mismatch')
        errors.extend('非平面动态路径：未确认三维岸壁相交，水面仅检查XY投影' for x in sources if x.get('flat') is False)
        for source in sources:
            if source.get('status') not in {None, 'fingerprint_mismatch'}:
                errors.append('网格来源状态未完成：' + str(source['status']))
            if type(source.get('flat')) is not bool or source.get('kind') not in {'dynamic', 'recipe'}:
                errors.append('网格来源缺明确类型或平面判定')
            for kind, count in [('wall_overlap', 'nonlocal_count'), ('water_fold', 'count')]:
                value = source.get(kind, {}).get(count)
                if type(value) is not int or value < 0:
                    errors.append('网格检查缺明确计数：' + kind)
        if not sources or v.get('error'):
            errors.append(v.get('error', '没有网格检查结果'))
        wall = any(x.get('wall_overlap', {}).get('nonlocal_count', 0) > 0 for x in sources)
        water = any(x.get('water_fold', {}).get('count', 0) > 0 for x in sources)
        visual_verdict = '未定' if errors else '风险待确认' if wall or water else '未见问题'
        visuals.append(dict(level_id=key, verdict=visual_verdict, wall_risk=wall, water_risk=water,
                            checks=[dict(kind='wall', name='非邻接岸壁网格重叠', risk=wall),
                                    dict(kind='water', name='水面中央带翻折', risk=water)], evidence=[evidence], errors=errors))
        detail_path = out.parent / evidence
        detail = read(detail_path)
        inline_visual = dict(v, sources=[{k: value for k, value in source.items()
            if k not in {'plot_water_triangles', 'plot_wall_triangles'}} for source in sources])
        detail.update(solver=s, visual=inline_visual, solver_budget=solver.get('budget'))
        if wall or water:
            # A positive counter cannot stand in for a real marked mesh.
            for source in sources:
                for kind, count in [('wall_overlap', 'nonlocal_count'), ('water_fold', 'count')]:
                    if source.get(kind, {}).get(count, 0) <= 0:
                        continue
                    hits = [h for h in source[kind].get('evidence', [])
                            if kind != 'wall_overlap' or h.get('nonlocal')]
                    if (not hits or not all(len(h.get('points', [])) in (3, 6) for h in hits)
                            or not source.get('plot_water_triangles') or not source.get('plot_wall_triangles')):
                        raise ValueError(key + ': positive visual risk lacks hit coordinates or production mesh')
            labels = (['岸壁重叠风险'] if wall else []) + (['水面折叠风险'] if water else [])
            steps = [f'读取本关 {key} 的 details 证据，核对 visual.sources 的来源、坐标和网格判定。',
                     '执行 scan_levels.py，对同份 Resources / Hotfix 配方与动态水道调用生产网格算法。',
                     '查看图中棕色三角片与红圈，对应 evidence 中 vertices；检查是否为非相邻段重叠或中央水面反向。',
                     '这是离线几何风险；尚未观察真实渲染，不把风险数量当已确认游戏 Bug。']
            detail['visual_whitebox_steps'] = steps
            triangles, points = [], []
            # Plot one coherent production source, rather than blending
            # different recipe meshes into an invented channel shape.
            risky_sources = [x for x in sources if x.get('water_fold', {}).get('count', 0)>0
                             or x.get('wall_overlap', {}).get('nonlocal_count', 0)>0]
            primary = next((x for x in risky_sources if x.get('kind') == 'dynamic'), risky_sources[0])
            for source in [primary]:
                for kind in ['water_fold', 'wall_overlap']:
                    for hit in source.get(kind, {}).get('evidence', []):
                        if kind == 'wall_overlap' and not hit.get('nonlocal'):
                            continue
                        # Probe supplies points in level-grid coordinates.
                        points.extend(hit.get('points', []))
                        pts = hit.get('points', [])
                        if len(pts) in (3, 6):
                            triangles.extend([pts[i:i+3] for i in range(0, len(pts), 3)])
            image = 'levels/images/risk-' + key.replace('/', '-') + '.png'
            draw_level(level, {**layout[key], **splines[key],
                'verdict': '几何风险待确认', 'visual_triangles': triangles,
                'expanded_path': primary.get('samples', []),
                'plot_water_triangles': primary.get('plot_water_triangles', []),
                'plot_wall_triangles': primary.get('plot_wall_triangles', []),
                'visual_issues': [dict(message='；'.join(labels), points=points)]}, out.parent/image)
            source_label = '动态回退网格' if primary.get('kind') == 'dynamic' else '资源配方网格'
            risks.append(dict(level_id=key, caption='；'.join(labels)+f'（图示{source_label}；其它来源另见证据）', image=image,
                              evidence=evidence, steps=steps, kind='visual-risk'))
        write(detail_path, detail)
        solver_label = ('已回放通关' if solved else '关卡输入不合法' if valid is False or s['status'] == 'Invalid'
                        else '已确认无解' if s['status'] == 'Unsolvable'
                        else '执行失败，未定' if s['status'] == 'ProbeError' else '预算内未定')
        table.append(dict(level_id=key, number=level['number'],
            structure='发现问题' if key in invalid else '未定' if key in validation_unknown else '未见问题',
            layout=layout[key]['verdict'], solvability=solver_label,
            visual=visual_verdict, evidence=evidence))
    total = len(levels)
    checked = sum(x['verdict'] != '未定' for x in solvability)
    success = sum(x['replay_completed'] for x in solvability)
    undecided = sum(x['verdict'] == '未定' for x in solvability)
    problems = sum(x['verdict'] == '发现问题' for x in solvability)
    write(out/'solvability-results.json', dict(schema_version=1, inventory=fragment['inventory_file'], total=total,
        checked=checked, attempted=total, results=solvability))
    solver_status = '检查未完成' if undecided else '发现问题' if problems else '检查完成未见问题'
    solver_summary = f'{total} 关全部执行；{success} 关找到无道具解并独立回放通关，{undecided} 关预算内未定，{problems} 关确认无解或输入不合法。未定不等于无解。'
    fragment['solvability'] = dict(status=solver_status, summary=solver_summary, total=total, checked=checked,
        run_ids=['RUN-LEVEL-SOLVER'], evidence=['levels/solvability-results.json','levels/solver-kernel-build/manifest.json'],
        result_file='levels/solvability-results.json')
    visual_checked = sum(x['verdict'] != '未定' for x in visuals)
    wall_count = sum(x['wall_risk'] for x in visuals)
    water_count = sum(x['water_risk'] for x in visuals)
    recipe_water = sum(any(s.get('kind') == 'recipe' and s.get('water_fold', {}).get('count', 0)>0 for s in v.get('sources', [])) for v in by_visual.values())
    visual_summary = f'{total} 关逐关生成/解码生产网格；{wall_count} 关岸壁重叠风险，{water_count} 关水面折叠风险（其中资源配方命中 {recipe_water} 关，同关多来源不重复计数），{total-visual_checked} 关未定。动态回退与资源配方分别留证，未证明设备实际选源；风险不是已确认游戏 Bug。'
    write(out/'visual-summary.json', dict(schema_version=1, inventory=fragment['inventory_file'], total=total,
        checked=visual_checked, results=visuals))
    visual_status = '检查未完成' if visual_checked < total else '有风险待确认' if risks else '检查完成未见问题'
    fragment['visual'] = dict(status=visual_status, total=total, checked=visual_checked, summary=visual_summary,
        result_file='levels/visual-summary.json', evidence=['levels/visual-summary.json','levels/visual-kernel-build/manifest.json'],
        wall_risk_count=wall_count, water_risk_count=water_count)
    package_bad = [f['path'] for f in inventory['files'] if not f['hotfix_matches']]
    structure_status = '检查未完成' if validation_unknown else '发现问题' if invalid else '检查完成未见问题'
    fragment.update(pipeline_version=2, risks=risks, table=table,
        summary_rows=[
            dict(id='structure', name='关卡配置是否合法', status=structure_status,
                 summary=f'正式 Validator 检查 {total-len(validation_unknown)}/{total} 关，{len(invalid)} 关不合法；颜色、数量及机关关联以逐关正式断言为准。', evidence=['levels/solvability-results.json']),
            dict(id='package', name='关卡打包是否一致', status='发现问题' if package_bad else '检查完成未见问题',
                 summary=f'{total} 关 manifest/分组已对账，{len(inventory["files"])} 个文件核对 Resources 与 Hotfix；{len(package_bad)} 个镜像不一致。指纹仅核对头字段，未重算生产内容指纹。', evidence=['levels/level-inventory.json']),
            dict(id='solver', name='无道具能否通关', status=solver_status, summary=solver_summary, evidence=['levels/solvability-results.json']),
            dict(id='wall', name='岸壁是否重叠', status='有风险待确认' if wall_count else '检查未完成' if visual_checked<total else '检查完成未见问题',
                 summary=f'{wall_count} 关有非邻接岸壁几何相交风险。动态回退与正式配方分开留证；不等于实际画面异常。', evidence=['levels/visual-summary.json']),
            dict(id='water', name='水面是否折叠', status='有风险待确认' if water_count else '检查未完成' if visual_checked<total else '检查完成未见问题',
                 summary=f'{water_count} 关有水面中央实体带翻面风险。图中标出真实三角片；不把不同高程投影相交当缺陷。', evidence=['levels/visual-summary.json'])])
    fragment['layout']['summary'] = fragment['layout']['summary'].replace('未执行逐关求解和完整机关规则验证。', '此项仅指基础布局，通关与表现网格见独立结果。')
    metadata = read(out/'run-metadata.json')
    metadata.update(production_full_validator_executed=not validation_unknown, solver_executed=True,
        visual_mesh_executed=True, solver_summary=solver_summary, visual_summary=visual_summary,
        summary=fragment['layout']['summary'] + ' ' + solver_summary + ' ' + visual_summary)
    write(out/'run-metadata.json', metadata)
    write(out/'report-fragment.json', fragment)
    print(solver_summary, flush=True)
    print(visual_summary, flush=True)
