"""Business-node projection. Reading legacy data never rewrites IDs or blocks."""
import copy
import re

DEFAULT_SKILL = '''# 自定义任务默认 Skill
## 输入
核对当前节点任务、资料来源、版本和上游交付。缺少必要信息时明确提出确认问题。
## 执行
按节点内的任务指令处理资料；区分事实、推断和未验证内容。不得编造工具调用、测试执行或外部发布。
## 输出
输出可交付正文、依据和覆盖缺口；使用明确的验收项，避免无关重复内容。
## 审核与边界
保留来源证据；存在歧义、权限不足或执行器缺失时说明限制，不自动批准或修改外部状态。
'''


def groups(blocks):
    """One reference/task per card; contiguous old primitives form one task."""
    result=[]
    for block in blocks:
        item=copy.deepcopy(block);config=item['config'];kind=item['type']
        if kind in ('node','task'):
            result.append({'id':item['id'],'name':config.get('label') or ('部门节点' if kind=='node' else '自定义任务'),
                           'description':config.get('description',''),'source_node':config.get('node','') if kind=='node' else '',
                           'kind':'reference' if kind=='node' else 'task','blocks':config.get('blocks',[]) if kind=='task' else [],
                           'inputs':config.get('inputs',''),'auto_next':config.get('auto_next',kind=='node'),
                           'config':config,'block_ids':[item['id']],'legacy':False})
        elif result and result[-1]['legacy']:
            result[-1]['blocks'].append(item);result[-1]['block_ids'].append(item['id'])
        else:
            result.append({'id':item['id'],'name':'自定义任务','description':'资料、AI 与审核积木',
                           'source_node':'','kind':'task','blocks':[item],'inputs':'','auto_next':True,
                           'config':{},'block_ids':[item['id']],'legacy':True})
    return result


def coordinate(flow, instance):
    return 'wf:'+flow+':'+instance


def validate_coordinate(store, project, value, *, current=False):
    if not isinstance(value,str) or not re.fullmatch(r'wf:[a-f0-9]{32}:[a-zA-Z0-9_-]{1,80}',value):
        raise ValueError('工作流节点范围无效')
    _,identity,instance=value.split(':')
    with store.connection() as db:
        row=db.execute('SELECT blocks FROM custom_flows WHERE project_id=? AND id=?',(project,identity)).fetchone()
    if not row:raise ValueError('工作流节点不属于当前项目')
    if current:
        import json
        if not any(g['id']==instance for g in groups(json.loads(row['blocks']))):raise ValueError('工作流节点不存在')
    return identity,instance
