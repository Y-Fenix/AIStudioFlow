"""Public snapshots: real SQLite/Policy identities, no model or external services."""
import base64
import hashlib
import json
import tempfile
import unittest
from server.store import Store
from server.core.identity import current_user
from server.core.admin import Administration
from server.core.public_area.service import PublicArea, Conflict


class PublicAreaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name + '/central.sqlite')
        self.studio = self.store.studios()[0]['id']
        self.project = self.store.create_project('Game', self.studio)['id']
        self.service = PublicArea(self.store)
        self.version = self.service.versions(self.studio, self.project, {'name': '1.0'})['id']
        with self.store.connection() as db:
            db.execute("INSERT INTO users(id,tenant_key,open_id,name,status) VALUES('alice','password','alice','Alice','active')")
            db.execute("INSERT INTO studio_memberships VALUES(?,'alice','member')", (self.studio,))
            db.execute("INSERT INTO team_members VALUES('alice',?,?,'testing','member')", (self.studio,self.project))
        self.package = dict(schema_version=1, title='Static review', description='Not a runtime pass',
            version_id=self.version, department='testing', node='testing:1', kind='result',
            source={'id':'local-result','revision':1,'digest':'a'*64}, content='Evidence only', attachments=[])

    def tearDown(self):
        self.tmp.cleanup()

    def grant(self, action, effect='allow'):
        return Administration(self.store).rule(dict(studio_id=self.studio,project_id=self.project,
            department='testing',node='',subject_type='user',subject_id='alice',
            resource='publication',action=action,effect=effect))['id']

    def stage(self, operation='operation-001', **extra):
        return self.service.stage(self.studio,self.project,dict(operation_id=operation,package=self.package,
            expected_revision=0,**extra))

    def publish(self, operation='operation-001'):
        self.stage(operation)
        return self.service.commit(self.studio,self.project,operation)

    def test_author_is_authenticated_not_client_supplied_and_snapshot_is_immutable(self):
        self.package['author_id']='local'
        with self.assertRaises(ValueError):self.stage()
        self.package.pop('author_id')
        self.grant('create'); self.grant('view')
        token=current_user.set('alice')
        try:
            result=self.publish()
            self.assertEqual(result['author_id'],'alice')
            self.package['content']='Edited locally'
            detail=self.service.detail(self.studio,self.project,result['id'])
            self.assertEqual(detail['package']['content'],'Evidence only')
        finally:current_user.reset(token)

    def test_membership_does_not_grant_publish_and_revocation_blocks_final_commit(self):
        token=current_user.set('alice')
        try:
            with self.assertRaises(PermissionError):self.stage()
        finally:current_user.reset(token)
        rule=self.grant('create')
        token=current_user.set('alice')
        try:self.stage()
        finally:current_user.reset(token)
        Administration(self.store).revoke(rule)
        token=current_user.set('alice')
        try:
            with self.assertRaises(PermissionError):self.service.commit(self.studio,self.project,'operation-001')
        finally:current_user.reset(token)
        self.assertEqual(self.service.listing(self.studio,self.project,{})['total'],0)

    def test_staging_is_private_idempotency_and_revision_conflicts(self):
        staged=self.stage()
        self.assertEqual(self.service.listing(self.studio,self.project,{})['total'],0)
        first=self.service.commit(self.studio,self.project,staged['operation_id'])
        self.assertEqual(first,self.service.commit(self.studio,self.project,staged['operation_id']))
        self.assertEqual(first,self.stage())
        self.package['content']='New revision'
        with self.assertRaises(Conflict):self.stage()
        self.service.stage(self.studio,self.project,dict(operation_id='operation-002',package=self.package,
            publication_id=first['id'],expected_revision=1))
        self.service.stage(self.studio,self.project,dict(operation_id='operation-003',package=self.package,
            publication_id=first['id'],expected_revision=1))
        second=self.service.commit(self.studio,self.project,'operation-002')
        self.assertEqual(second['revision'],2)
        with self.assertRaises(Conflict):self.service.commit(self.studio,self.project,'operation-003')
        self.assertEqual(self.service.detail(self.studio,self.project,first['id'],1)['package']['content'],'Evidence only')

    def test_attachment_integrity_private_paths_and_withdrawal(self):
        data=b'hello'
        self.package['attachments']=[{'name':'proof.txt','data':base64.b64encode(data).decode(),
            'sha256':hashlib.sha256(data).hexdigest()}]
        self.package['attachments'][0]['sha256']='0'*64
        with self.assertRaises(ValueError):self.stage()
        self.package['attachments'][0]['sha256']=hashlib.sha256(data).hexdigest()
        self.package['attachments'][0]['name']='../proof.txt'
        with self.assertRaises(ValueError):self.stage()
        self.package['attachments'][0]['name']='proof.txt'
        self.package['content']='Evidence in /Users/alice/private/game.cs and C:\\Users\\Alice\\game.cs'
        result=self.publish()
        detail=self.service.detail(self.studio,self.project,result['id'])
        self.assertNotIn('/Users/alice',json.dumps(detail))
        self.assertNotIn('Alice\\\\game',json.dumps(detail))
        self.assertNotIn('data',detail['package']['attachments'][0])
        self.assertEqual(self.service.attachment(self.studio,self.project,result['id'],1,0)['data'],base64.b64encode(data).decode())
        self.service.withdraw(self.studio,self.project,result['id'],1)
        with self.assertRaises(KeyError):self.service.detail(self.studio,self.project,result['id'],1)
        with self.assertRaises(KeyError):self.service.attachment(self.studio,self.project,result['id'],1,0)

    def test_expired_stages_are_cleaned_without_affecting_published_snapshots(self):
        first=self.publish()
        self.stage('abandoned-001')
        with self.store.connection() as db:
            db.execute('UPDATE public_operations SET expires=0 WHERE result IS NULL')
        self.service.cleanup()
        with self.store.connection() as db:
            self.assertIsNone(db.execute("SELECT package FROM public_operations WHERE operation_id='abandoned-001'").fetchone()[0])
        self.assertEqual(self.service.detail(self.studio,self.project,first['id'])['package']['content'],'Evidence only')

    def test_public_notification_only_enqueued_once_after_commit_and_personal_suppressed(self):
        from unittest.mock import patch
        from server.core.notifications import enqueue
        config={'enabled':True,'webhook':'test-only-not-sent','events':['public_published'],'target_hash':'test'}
        with patch('server.core.notifications.NotificationSettings.effective',return_value=config):
            self.stage()
            with self.store.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM node_notifications').fetchone()[0],0)
            self.service.commit(self.studio,self.project,'operation-001')
            self.service.commit(self.studio,self.project,'operation-001')
            with self.store.connection() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM node_notifications').fetchone()[0],1)
                self.store.runtime_mode='personal'
                self.assertIsNone(enqueue(self.store,db,self.project,'testing:1','personal-operation','public_published'))
                self.assertEqual(db.execute('SELECT COUNT(*) FROM node_notifications').fetchone()[0],1)

    def test_cross_project_and_source_coordinates_rejected(self):
        other=self.store.create_project('Other',self.studio)['id']
        with self.assertRaises(ValueError):self.service.stage(self.studio,other,dict(operation_id='operation-001',package=self.package,expected_revision=0))
        self.package['department']='product'
        with self.assertRaises(ValueError):self.stage()
        self.package['department']='testing'
        self.package['source']['digest']='invalid'
        with self.assertRaises(ValueError):self.stage()


if __name__=='__main__':unittest.main()
