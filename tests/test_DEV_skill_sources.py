import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DEV_SkillSourcesTests(unittest.TestCase):
    def test_technical_plan_cites_adapted_architecture_decision_skill(self):
        skill = (ROOT / 'departments/development/skills/0.md').read_text(encoding='utf-8')
        manifest = json.loads((ROOT / 'departments/development/manifest.json').read_text(encoding='utf-8'))

        self.assertEqual(manifest['nodes'][0][0], '技术方案')
        self.assertIn('Claude-Code-Game-Studios', skill)
        self.assertIn('architecture-decision/SKILL.md', skill)
        self.assertIn('MIT', skill)
        self.assertIn('不擅自提交、拉取或推送 Git', skill)


if __name__ == '__main__':
    unittest.main()
