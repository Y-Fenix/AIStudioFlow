"""Persistent studio node workspaces with atomic revision checks."""
import hashlib
import json
from server.core.identity import user_id
from server.node_skills import validate
from server.studio_catalog import default_skill, node_definition


class Workspaces:
    def __init__(self, store):
        self.store = store

    def _check(self, db, studio_id, project_id):
        row = db.execute('''SELECT p.* FROM projects p JOIN studio_memberships m ON m.studio_id=p.studio_id
            WHERE p.id=? AND p.studio_id=? AND m.user_id=? AND p.archived=0 ''', (project_id, studio_id, user_id())).fetchone()
        if row is None:
            raise KeyError('项目不属于当前工作室')
        return row

    def _read(self, db, studio_id, project_id, node):
        node_definition(node,self.store,project_id)
        self._check(db, studio_id, project_id)
        row = db.execute('SELECT * FROM studio_workspaces WHERE project_id=? AND node=?', (project_id, node)).fetchone()
        value = dict(row) if row else {'project_id': project_id, 'node': node, 'inputs': '', 'deliverable': '',
                                      'status': 'not_started', 'revision': 0, 'updated_at': None, 'skill': None}
        value['skill'] = json.loads(value['skill']) if value['skill'] else default_skill(node,self.store,project_id)
        from server.core.skill_library import bound_skill
        value['skill'] = bound_skill(db,project_id,node,value['skill'])
        value['studio_id'] = studio_id
        value['events'] = [dict(r) for r in db.execute('''SELECT action,detail,created_at FROM studio_events
            WHERE project_id=? AND node=? ORDER BY id''', (project_id, node))]
        return value

    def get(self, studio_id, project_id, node):
        with self.store.connection() as db:
            return self._read(db, studio_id, project_id, node)

    def save(self, studio_id, project_id, node, value):
        from server.core.project_nodes import project_records
        if any(n['id']==node and n['archived'] for n in project_records(self.store,project_id)):
            raise ValueError('节点已归档，历史记录仅供查看')
        if not isinstance(value, dict):
            raise ValueError('工作区内容必须为对象')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            from server.core.project_content import require_enabled
            require_enabled(db,project_id,node.split(':')[0])
            current = self._read(db, studio_id, project_id, node)
            if type(value.get('revision')) is not int or value['revision'] != current['revision']:
                raise ValueError('节点已变化，请刷新后再保存')
            inputs = value.get('inputs', current['inputs'])
            deliverable = value.get('deliverable', current['deliverable'])
            if not all(isinstance(x, str) and len(x.encode()) <= 800000 for x in (inputs, deliverable)):
                raise ValueError('节点内容过大或格式错误')
            skill = current['skill']
            if 'skill' in value:
                from server.core.skill_library import SkillLibrary
                SkillLibrary(self.store)._writable(db,project_id,node)
                raw = value['skill']
                if raw is None:
                    skill = default_skill(node,self.store,project_id)
                else:
                    if isinstance(raw, str): raw = {'content': raw}
                    if not isinstance(raw, dict): raise ValueError('Skill 格式错误')
                    content = validate(raw.get('content'))
                    skill = {'name': str(raw.get('name') or '用户 Skill')[:200], 'content': content,
                             'source_kind': 'imported', 'sha256': hashlib.sha256(content.encode()).hexdigest()}
                from server.core.skill_library import append_version
                append_version(db,self.store,project_id,node,skill,str(value.get('skill_note') or '节点工作区导入 / 恢复规则')[:2000])
            status = 'waiting_user' if deliverable.strip() else 'draft'
            db.execute('''INSERT INTO studio_workspaces(project_id,node,inputs,skill,deliverable,status,revision)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(project_id,node) DO UPDATE SET inputs=excluded.inputs,skill=excluded.skill,
                deliverable=excluded.deliverable,status=excluded.status,revision=excluded.revision,updated_at=CURRENT_TIMESTAMP''',
                (project_id, node, inputs, json.dumps(skill, ensure_ascii=False), deliverable, status, current['revision']+1))
            db.execute('INSERT INTO studio_events(project_id,node,action,detail) VALUES(?,?,?,?)',
                       (project_id, node, 'workspace_saved', '保存节点' + ('输入、' if 'inputs' in value else '') +
                        ('交付物、' if 'deliverable' in value else '') + ('Skill' if 'skill' in value else '资料')))
        return self.get(studio_id, project_id, node)

    def decide(self, studio_id, project_id, node, value):
        from server.core.project_nodes import project_records
        if any(n['id']==node and n['archived'] for n in project_records(self.store,project_id)):
            raise ValueError('节点已归档，历史记录仅供查看')
        if not isinstance(value, dict) or value.get('action') not in ('approve', 'reject'):
            raise ValueError('审批动作无效')
        reason = value.get('reason')
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 2000:
            raise ValueError('请填写1至2000字的决策理由')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            from server.core.project_content import require_enabled
            require_enabled(db,project_id,node.split(':')[0])
            current = self._read(db, studio_id, project_id, node)
            if type(value.get('revision')) is not int or value['revision'] != current['revision']:
                raise ValueError('节点已变化，请刷新')
            if not current['deliverable'].strip(): raise ValueError('没有交付物，不能审批')
            if current['status'] not in ('waiting_user', 'rejected'): raise ValueError('当前交付物已确认或不可审批')
            db.execute('''UPDATE studio_workspaces SET status=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP
                WHERE project_id=? AND node=?''',
                ('approved' if value['action'] == 'approve' else 'rejected', project_id, node))
            db.execute('INSERT INTO studio_events(project_id,node,action,detail) VALUES(?,?,?,?)',
                       (project_id, node, 'human_decision', ('确认交付：' if value['action']=='approve' else '退回修改：') + reason.strip()))
            if value['action'] == 'approve':
                from server.core.node_continuation import record_completion
                record_completion(self.store,db,studio_id,project_id,node,current['revision']+1)
        return self.get(studio_id, project_id, node)

    def summary(self, studio_id, project_id):
        with self.store.connection() as db:
            self._check(db, studio_id, project_id)
            nodes = [dict(r) for r in db.execute('''SELECT node,status,revision,updated_at,
                length(trim(deliverable))>0 AS has_deliverable FROM studio_workspaces WHERE project_id=?''', (project_id,))]
            tasks = [dict(r) for r in db.execute('''SELECT id,title,stage,status,revision FROM tasks
                WHERE project_id=? ORDER BY rowid DESC''', (project_id,))]
        return {'nodes': nodes, 'tasks': tasks}
