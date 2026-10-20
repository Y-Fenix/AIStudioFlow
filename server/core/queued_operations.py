"""Authorization for legacy QA jobs under the actor who enqueued the work."""
from pathlib import Path

from server.core.permissions import AccessDenied, Policy


def authorize_testing_job(store, job):
    actor = job.get('actor')
    stage = {'generate': 0, 'execute': 1, 'attribution': 2, 'regression': 5}.get(job.get('kind', 'generate'))
    if not actor or stage is None:
        raise AccessDenied('任务缺少有效创建者或执行节点，请重新提交')
    with store.connection() as db:
        project = db.execute('''SELECT p.studio_id,p.archived AS project_archived,s.archived AS studio_archived
            FROM projects p JOIN studios s ON s.id=p.studio_id WHERE p.id=?''', (job['project_id'],)).fetchone()
    if not project or project['project_archived'] or project['studio_archived']:
        raise AccessDenied('任务所属工作室或项目已归档')
    policy = Policy(store)
    scope = {'studio': project['studio_id'], 'project': job['project_id'], 'node': f'testing:{stage}', 'actor': actor}
    for action in ('view', 'execute'):
        policy.require('node', action, **scope)
    if stage and not policy.allowed('platform', 'manage', actor=actor):
        with store.connection() as db:
            connection = db.execute('SELECT repository FROM project_connections WHERE project_id=?', (job['project_id'],)).fetchone()
        binding = store.task(job['project_id'], job['task_id']).get('binding', {})
        repository = binding.get('repository')
        if not connection or not connection['repository'] or not repository or (
                Path(repository).expanduser().resolve() != Path(connection['repository']).expanduser().resolve()):
            raise AccessDenied('代码目录授权已变化，请由负责人核对项目接入并重新绑定')
