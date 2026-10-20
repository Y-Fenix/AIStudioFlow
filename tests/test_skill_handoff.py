import tempfile
import time
import unittest
from urllib.parse import parse_qs, urlsplit

from server.store import Store
from server.core.identity import current_user
from server.core.skill_handoff import SkillHandoff


class SkillHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name + '/db.sqlite')
        self.studio = self.store.studios()[0]['id']
        self.project = self.store.create_project('游戏', self.studio)['id']
        with self.store.connection() as db:
            db.execute("INSERT INTO users(id,tenant_key,open_id,name,status) VALUES('artist','t','a','美术','active')")
        with self.store.connection() as db:
            db.execute('INSERT INTO studio_memberships(studio_id,user_id,role) VALUES(?,?,?)', (self.studio, 'artist', 'member'))
            db.execute('INSERT INTO team_members(user_id,studio_id,project_id,department,role) VALUES(?,?,?,?,?)',
                       ('artist', self.studio, self.project, 'design', 'member'))
        self.handoff = SkillHandoff(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def test_bridge_origin_rejects_paths_queries_fragments_and_non_loopback_http(self):
        from server.core.skill_handoff import validate_origin
        for origin in (
            'https://studio.example/path',
            'https://studio.example/?token=secret',
            'https://studio.example/#fragment',
            'http://studio.example',
            'https://user@studio.example',
        ):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                validate_origin(origin)

    def test_bridge_origin_accepts_https_and_explicit_loopback_http(self):
        from server.core.skill_handoff import validate_origin
        self.assertEqual(validate_origin('https://studio.example:8443'), 'https://studio.example:8443')
        self.assertEqual(validate_origin('http://127.0.0.1:8766/'), 'http://127.0.0.1:8766')

    def test_export_permission_is_required_to_create_a_ticket(self):
        context_token = current_user.set('artist')
        try:
            with self.assertRaises(PermissionError):
                self.handoff.create(self.studio, self.project, 'testing:0', 'http://127.0.0.1:8766')
        finally:
            current_user.reset(context_token)

    def test_manual_recovery_uses_the_same_prompt_without_creating_a_ticket(self):
        from server.studio_workspaces import Workspaces
        workspace = Workspaces(self.store)
        content = '# 自定义规则\n保留原文，并检查缺失附件。'
        workspace.save(self.studio, self.project, 'design:0', {'revision': 0, 'skill': content})
        preview = self.handoff.create(self.studio, self.project, 'design:0', 'http://127.0.0.1:8766', preview=True)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM codex_handoffs').fetchone()[0], 0)
        ticket = self.handoff.create(self.studio, self.project, 'design:0', 'http://127.0.0.1:8766')
        token = parse_qs(urlsplit(ticket['uri']).query)['ticket'][0]
        redeemed = self.handoff.redeem(token, 'http://127.0.0.1:8766')
        self.assertEqual(preview['prompt'], redeemed['prompt'])
        self.assertIn(content, preview['prompt'])
        self.assertEqual(workspace.get(self.studio, self.project, 'design:0')['skill']['content'], content)

    def test_manual_recovery_requires_export_permission(self):
        with self.store.connection() as db:
            db.execute("INSERT INTO permission_rules(id,subject_type,subject_id,studio_id,project_id,department,node,resource,action,effect,created_by) VALUES('deny-export','user','artist',?,?, 'design','design:0','skill','export','deny','local')", (self.studio, self.project))
        token = current_user.set('artist')
        try:
            with self.assertRaises(PermissionError):
                self.handoff.create(self.studio, self.project, 'design:0', 'http://127.0.0.1:8766', preview=True)
        finally:
            current_user.reset(token)

    def test_ticket_returns_bound_skill_once_and_never_twice(self):
        context_token = current_user.set('artist')
        try:
            with self.store.connection() as db:
                db.execute("UPDATE team_members SET department='testing' WHERE user_id='artist'")
            with self.store.connection() as db:
                db.execute("INSERT INTO permission_rules(id,subject_type,subject_id,studio_id,project_id,department,node,resource,action,effect,created_by) VALUES('grant','user','artist',?,?, 'testing','testing:0','skill','export','allow','local')", (self.studio, self.project))
            ticket = self.handoff.create(self.studio, self.project, 'testing:0', 'http://127.0.0.1:8766')
            ticket_token = parse_qs(urlsplit(ticket['uri']).query)['ticket'][0]
            result = self.handoff.redeem(ticket_token, 'http://127.0.0.1:8766')
            self.assertEqual(result['node'], 'testing:0')
            self.assertIn('~/.codex/skills/studioflow-testing-1/SKILL.md', result['prompt'])
            self.assertIn('#', result['prompt'])
            with self.assertRaises(PermissionError):
                self.handoff.redeem(ticket_token, 'http://127.0.0.1:8766')
        finally:
            current_user.reset(context_token)

    def test_expired_ticket_cannot_be_redeemed(self):
        context_token = current_user.set('local')
        try:
            ticket = self.handoff.create(self.studio, self.project, 'design:0', 'http://127.0.0.1:8766')
            ticket_token = parse_qs(urlsplit(ticket['uri']).query)['ticket'][0]
            import hashlib
            digest = hashlib.sha256(ticket_token.encode()).hexdigest()
            with self.store.connection() as db:
                db.execute('UPDATE codex_handoffs SET expires=? WHERE token_hash=?', (time.time()-1, digest))
            with self.assertRaises(PermissionError):
                self.handoff.redeem(ticket_token, 'http://127.0.0.1:8766')
        finally:
            current_user.reset(context_token)

    def test_inactive_creator_cannot_redeem_existing_ticket(self):
        context_token = current_user.set('local')
        try:
            ticket = self.handoff.create(self.studio, self.project, 'design:0', 'http://127.0.0.1:8766')
            ticket_token = parse_qs(urlsplit(ticket['uri']).query)['ticket'][0]
            with self.store.connection() as db:
                db.execute("UPDATE users SET status='disabled' WHERE id='local'")
            with self.assertRaises(PermissionError):
                self.handoff.redeem(ticket_token, 'http://127.0.0.1:8766')
        finally:
            current_user.reset(context_token)

    def test_revoked_skill_export_permission_invalidates_unredeemed_ticket(self):
        context_token = current_user.set('artist')
        try:
            with self.store.connection() as db:
                db.execute("UPDATE team_members SET department='testing' WHERE user_id='artist'")
                db.execute("INSERT INTO permission_rules(id,subject_type,subject_id,studio_id,project_id,department,node,resource,action,effect,created_by) VALUES('grant','user','artist',?,?, 'testing','testing:0','skill','export','allow','local')", (self.studio, self.project))
            ticket = self.handoff.create(self.studio, self.project, 'testing:0', 'http://127.0.0.1:8766')
            ticket_token = parse_qs(urlsplit(ticket['uri']).query)['ticket'][0]
            with self.store.connection() as db:
                db.execute("UPDATE permission_rules SET effect='deny' WHERE id='grant'")
            with self.assertRaises(PermissionError):
                self.handoff.redeem(ticket_token, 'http://127.0.0.1:8766')
        finally:
            current_user.reset(context_token)

    def test_library_handoff_rejects_changed_rule_instead_of_exporting_unseen_content(self):
        workspace=__import__('server.studio_workspaces',fromlist=['Workspaces']).Workspaces(self.store)
        original=workspace.get(self.studio,self.project,'design:0')['skill']
        workspace.save(self.studio,self.project,'design:0',{'revision':0,'skill':'新规则，与详情内容不同'})
        with self.assertRaisesRegex(ValueError,'规则已变化'):
            self.handoff.create(self.studio,self.project,'design:0','http://127.0.0.1:8766',expected_sha256=original['sha256'])
        with self.store.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM codex_handoffs').fetchone()[0],0)


if __name__ == '__main__':
    unittest.main()
