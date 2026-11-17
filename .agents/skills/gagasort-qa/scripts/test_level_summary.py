#!/usr/bin/env python3
"""真实汇总入口的证据门禁；测试输入仅隔离阶段产物，不模拟求解规则。"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch, MagicMock

import summarize_level_checks as summary
import scan_levels


class LevelSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name) / 'levels'
        self.out.mkdir()
        self.key = 'default/0/1'
        self.levels = [dict(level_id=self.key, number=1)]
        self.solver = dict(level_id=self.key, status='Solvable', validation=dict(valid=True),
                           replay=dict(has_completed=True, independent_runtime=True))
        self.source = dict(kind='dynamic', flat=True,
            water_fold=dict(count=0, status='checked_xy_flat'),
            wall_overlap=dict(nonlocal_count=0, status='checked_xy_flat'))
        self.visual = dict(level_id=self.key, sources=[self.source])
        self.draws = []

    def run_summary(self, solver_rows=None, visual_rows=None):
        artifacts = {
            'report-fragment.json': dict(inventory_file='levels/level-inventory.json', layout=dict(summary='布局')),
            'solver-kernel.json': dict(levels=solver_rows if solver_rows is not None else [self.solver]),
            'visual-results.json': dict(levels=visual_rows if visual_rows is not None else [self.visual]),
            'layout-results.json': dict(results=[dict(level_id=self.key, verdict='未见问题')]),
            'spline-kernel.json': dict(levels=[dict(level_id=self.key,
                expanded_path=[[0, 0], [1, 1]])]),
            'run-metadata.json': {}, 'details/default-0-1.json': {}}
        for name, data in artifacts.items():
            summary.write(self.out / name, data)
        summary.complete(self.out, self.levels, dict(files=[]),
                         lambda level, result, target: self.draws.append(result))
        return summary.read(self.out / 'report-fragment.json')

    def test_only_completed_independent_replay_is_success(self):
        self.assertEqual(self.run_summary()['solvability']['status'], '检查完成未见问题')
        metadata = summary.read(self.out / 'run-metadata.json')
        self.assertIn(metadata['solver_summary'], metadata['summary'])
        self.assertIn(metadata['visual_summary'], metadata['summary'])
        for replay in ({}, dict(has_completed=True, independent_runtime=False),
                       dict(has_completed=False, independent_runtime=True)):
            with self.subTest(replay=replay):
                self.solver['replay'] = replay
                self.assertEqual(self.run_summary()['solvability']['status'], '检查未完成')

    def test_invalid_validator_cannot_be_solved_green(self):
        self.solver['validation']['valid'] = False
        self.assertNotEqual(self.run_summary()['solvability']['status'], '检查完成未见问题')

    def test_solver_missing_wrong_or_duplicate_ids_are_rejected(self):
        for rows in ([], [dict(self.solver, level_id='wrong')], [self.solver, self.solver]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.run_summary(solver_rows=rows)

    def test_visual_missing_wrong_or_duplicate_ids_are_rejected(self):
        for rows in ([], [dict(self.visual, level_id='wrong')], [self.visual, self.visual]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.run_summary(visual_rows=rows)

    def test_layout_geometry_and_spline_reject_missing_wrong_and_duplicate_ids(self):
        correct = [dict(level_id=self.key)]
        for stage in ('geometry', 'spline'):
            for rows in ([], [dict(level_id='wrong')], correct * 2):
                with self.subTest(stage=stage, rows=rows):
                    for name in ('geometry', 'spline'):
                        summary.write(self.out / (name + '-kernel.json'),
                                      dict(levels=rows if stage == name else correct))
                    with self.assertRaises(ValueError):
                        scan_levels.finalize(self.out, self.out, dict(files=[]), self.levels)

    def test_nonflat_fingerprint_mismatch_and_missing_sources_are_not_green(self):
        for sources in ([dict(self.source, flat=False)],
                        [dict(kind='recipe', status='fingerprint_mismatch')], []):
            with self.subTest(sources=sources):
                self.visual['sources'] = sources
                self.assertEqual(self.run_summary()['visual']['status'], '检查未完成')

    def test_missing_mesh_checks_cannot_be_green(self):
        self.visual['sources'] = [dict(kind='dynamic', flat=True)]
        self.assertEqual(self.run_summary()['visual']['status'], '检查未完成')

    def test_unknown_status_missing_flat_and_invalid_counts_cannot_be_green(self):
        for change in (dict(status='unknown'), dict(flat=None),
                       dict(water_fold=dict(count=-1))):
            with self.subTest(change=change):
                self.visual['sources'] = [dict(self.source, **change)]
                self.assertEqual(self.run_summary()['visual']['status'], '检查未完成')
        self.visual['sources'] = [dict(self.source, water_fold=dict(count=True))]
        with self.assertRaises(ValueError):
            self.run_summary()

    def test_positive_risk_without_evidence_or_mesh_cannot_be_complete(self):
        self.source['water_fold'] = dict(count=1, evidence=[])
        with self.assertRaisesRegex(ValueError, 'positive visual risk'):
            self.run_summary()
        self.assertEqual(self.draws, [])

    def test_risk_plot_keeps_one_source_and_exact_grid_coordinates(self):
        points = [[12.25, -3.5], [13.25, -3.5], [12.25, -2.5]]
        self.source['water_fold'] = dict(count=1, evidence=[dict(points=points)])
        self.source['plot_water_triangles'] = [points]
        self.source['plot_wall_triangles'] = [points]
        self.source['samples'] = [[12.25, -3.5], [12.25, -2.5]]
        other = dict(kind='recipe', flat=True, water_fold=dict(count=1,
            evidence=[dict(points=[[90, 90], [91, 90], [90, 91]])]),
            wall_overlap=dict(nonlocal_count=0),
            plot_water_triangles=[[[90, 90], [91, 90], [90, 91]]],
            plot_wall_triangles=[[[90, 90], [91, 90], [90, 91]]])
        self.visual['sources'].append(other)
        self.run_summary()
        self.assertEqual(len(self.draws), 1)
        self.assertEqual(self.draws[0]['visual_triangles'], [points])
        self.assertEqual(self.draws[0]['plot_water_triangles'], [points])
        self.assertEqual(self.draws[0]['visual_issues'][0]['points'], points)
        self.assertEqual(self.draws[0]['expanded_path'], self.source['samples'])

    def test_draw_viewport_contains_remote_mesh_and_risk_coordinates(self):
        # Exercise the actual plotting transform, isolating only text/raster IO.
        points = [[1000, -700], [1001, -700], [1000, -699]]
        level = dict(level_id=self.key, nodes=[[0, 0], [1, 1]], board_size=10, loop_mode=1)
        result = dict(verdict='风险', plot_water_triangles=[points],
                      visual_triangles=[points], visual_issues=[dict(message='风险', points=points)])
        painter = MagicMock()
        with patch('PIL.ImageDraw.Draw', return_value=painter), \
             patch('PIL.ImageFont.truetype'), patch('PIL.Image.Image.save'):
            scan_levels.draw_level(level, result, self.out / 'risk.png')
        polygons = painter.polygon.call_args_list
        self.assertEqual(len(polygons), 2)
        for call in polygons:
            for x, y in call.args[0]:
                self.assertGreaterEqual(x, 0)
                self.assertLess(x, 760)
                self.assertGreaterEqual(y, 0)
                self.assertLess(y, 760)


if __name__ == '__main__':
    unittest.main()
