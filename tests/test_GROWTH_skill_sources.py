import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GROWTH_SkillSourcesTests(unittest.TestCase):
    def test_launch_readiness_cites_adapted_game_launch_checklist(self):
        skill = (ROOT / 'departments/growth/skills/0.md').read_text(encoding='utf-8')
        manifest = json.loads((ROOT / 'departments/growth/manifest.json').read_text(encoding='utf-8'))

        self.assertEqual(manifest['nodes'][0][0], '上线准备')
        self.assertIn('Claude-Code-Game-Studios', skill)
        self.assertIn('launch-checklist/SKILL.md', skill)
        self.assertIn('MIT', skill)
        self.assertIn('未接通', skill)
        self.assertIn('未经确认不提交商店或对外发布', skill)


if __name__ == '__main__':
    unittest.main()
