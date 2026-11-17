"""Game QA defaults must include pinned game methods, not security-only criteria."""
import unittest
from server.node_skills import defaults


class QA_SkillAdaptationTests(unittest.TestCase):
    def test_case_planning_and_evidence_review_use_game_specific_sources(self):
        skills = defaults()
        self.assertIn('game/qa-plan', skills['0']['upstream_sources'])
        self.assertIn('game/test-evidence-review', skills['1']['upstream_sources'])
        self.assertIn('game/test-evidence-review', skills['5']['upstream_sources'])
        self.assertNotIn('Drop cosmetic drift; keep boundary-crossing drift.', skills['1']['content'])


if __name__ == '__main__':
    unittest.main()
