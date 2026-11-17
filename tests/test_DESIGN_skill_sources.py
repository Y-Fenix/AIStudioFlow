import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DESIGN_SkillSourcesTests(unittest.TestCase):
    def test_asset_acceptance_cites_adapted_game_asset_audit(self):
        skill = (ROOT / 'departments/design/skills/3.md').read_text(encoding='utf-8')
        manifest = json.loads((ROOT / 'departments/design/manifest.json').read_text(encoding='utf-8'))

        self.assertEqual(manifest['nodes'][3][0], '设计验收')
        self.assertIn('Claude-Code-Game-Studios', skill)
        self.assertIn('asset-audit/SKILL.md', skill)
        self.assertIn('MIT', skill)
        self.assertIn('未评估', skill)
        self.assertIn('未接通', skill)


if __name__ == '__main__':
    unittest.main()
