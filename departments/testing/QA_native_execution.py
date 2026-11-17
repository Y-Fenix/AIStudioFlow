"""Shared project investigation with independent, source-validated case checkpoints.

Capabilities are injected by the platform; this module has no database or model access.
"""
import copy
import json
import os
import time
from .QA_native_review import (QA_NATIVE_VERSION, QA_plan_batches, QA_agent_schema, QA_agent_prompt,
                              QA_validate_agent_batch, QA_agent_rows, QA_repair_prompt)
from .QA_review_checkpoints import QA_checkpoint_path, QA_read_checkpoint, QA_write_checkpoint
from .QA_review_pool import QA_map_reviews


def QA_run_agent_reviews(cases, requirements, *, root, read_source, validate_case, agent,
                         skill, identity, baseline, directory, workers, check_cancelled,
                         cancellation_scope, progress=None, diagnostic=None, points=None, repair_request=None):
    results = [None] * len(cases)
    finished, reused = set(), set()
    import threading
    lock = threading.RLock()
    def QA_emit(case, event, model=False):
        with lock:
            callback = diagnostic if model else progress
            if callback:
                callback({**event, 'completed': len(finished), 'total': len(cases),
                          'case_id': case['id'], 'title': case['title'], 'workers': workers,
                          'checkpoint_reused_count': len(reused), 'reviewed_count': len(finished)-len(reused),
                          'execution_engine': 'project_agent'})
    def QA_signature(case):
        return QA_checkpoint_path([QA_NATIVE_VERSION, baseline, case, requirements, skill, identity])
    def QA_store(index, case, row, trace, cached=False):
        check_cancelled()
        path = directory / f'case-{index+1:04d}.json'
        row = copy.deepcopy(row)
        row['evidence'] = str(path)
        path.write_text(json.dumps({'case': case, 'baseline': baseline, 'result': row, 'trace': trace}, ensure_ascii=False, indent=2))
        path.chmod(0o600)
        with lock:
            results[index] = row
            finished.add(index)
            if cached:
                reused.add(index)
            QA_emit(case, {'state': 'case_completed', 'last_status': row['status']})
    pending = []
    for index, case in enumerate(cases):
        check_cancelled()
        cached = QA_read_checkpoint(QA_signature(case))
        if cached:
            try:
                assertions = cached['result']['assertions']
                live = {r['file']: read_source(r['file']) for a in assertions for r in a['call_chain']}
                checked = validate_case({'assertions': assertions}, case, live)
                canonical = copy.deepcopy(cached['result'])
                canonical.pop('evidence', None)
                for a in canonical['assertions']:
                    a.pop('model_reported_step_index', None)
                    for ref in a['call_chain']:
                        ref.pop('model_reported_line', None)
                if checked != canonical or not isinstance(cached['trace'], dict):
                    raise ValueError('检查点引用或结构变化')
                QA_store(index, case, checked, cached['trace'], cached=True)
                continue
            except (ValueError, KeyError, TypeError):
                pass
        pending.append((index, case))
    try:
        batch_size = int(os.environ.get('TESTFLOW_AGENT_BATCH_SIZE', '20'))
    except ValueError:
        raise ValueError('项目Agent工作包大小须为1至20') from None
    batches = [[pending[i] for i, _ in b] for b in QA_plan_batches([c for _, c in pending], points, size=batch_size)]
    def QA_review(batch_index, batch):
        check_cancelled()
        started = time.monotonic()
        package_cases = [c for _, c in batch]
        prompt = QA_agent_prompt(package_cases, requirements, skill)
        trace = {'execution_engine': 'project_agent', 'case_ids': [c['id'] for c in package_cases], 'attempts': []}
        first = package_cases[0]
        QA_emit(first, {'state': 'preparing', 'batch': batch_index+1, 'batch_total': len(batches)})
        output = agent.request_json(prompt, root, QA_agent_schema(package_cases),
                     audit_dir=directory / f'agent-{batch_index+1:03d}-1',
                     progress=lambda e: QA_emit(first, {**e, 'batch': batch_index+1, 'batch_total': len(batches)}, True))
        trace['attempts'].append(output)
        check_cancelled()
        by_id=QA_agent_rows(output,package_cases)
        failed=[]
        all_sources={}
        # Save valid cases before attempting a correction. One broken quote must
        # never discard the other independently validated cases in this package.
        for index,case in batch:
            try:
                rows,sources=QA_validate_agent_batch({'results':[by_id[case['id']]]},[case],read_source,validate_case)
                all_sources.update(sources)
                case_trace={**trace,'sources':sources}
                QA_write_checkpoint(QA_signature(case), {'result': rows[0], 'trace': case_trace})
                QA_store(index,case,rows[0],case_trace)
            except ValueError as exc:
                failed.append((index,case,str(exc)))
        trace['repairs']=[]
        for index,case,error in failed:
            check_cancelled()
            QA_emit(case,{'state':'validation_repair','validation_attempt':1,'validation_max_attempts':1})
            correction_prompt=QA_repair_prompt(case,by_id[case['id']],error,requirements,read_source)
            callback=lambda e:QA_emit(case,e,True)
            if repair_request is not None:
                correction=repair_request(correction_prompt,progress=callback)
            else:
                correction=agent.request_json(correction_prompt,root,QA_agent_schema([case]),progress=callback,
                                               audit_dir=directory/f'repair-{index+1:04d}')
            trace['repairs'].append({'case_id':case['id'],'validation_error':error,'output':correction})
            try:
                rows,sources=QA_validate_agent_batch(correction,[case],read_source,validate_case)
            except ValueError as exc:
                trace['validation_error']=str(exc)
                assertions = [{'step_index': i, 'status': 'insufficient_evidence',
                               'reasoning': '模型输出的源码证据校验失败，无法确定此步骤结果。',
                               'precondition_analysis': '未能验证模型提供的前置条件。',
                               'counterexample_search': '未能验证模型提供的反例或调用链。',
                               'call_chain': [], 'gap': '源码证据校验失败：'+str(exc),
                               'next_action': '重新执行此用例并核对源码引用。'}
                              for i, _ in enumerate(case['steps'])]
                row = validate_case({'assertions': assertions}, case, {})
                QA_store(index, case, row, {**trace, 'sources': {}})
                continue
            all_sources.update(sources)
            case_trace={**trace,'sources':sources}
            QA_write_checkpoint(QA_signature(case), {'result': rows[0], 'trace': case_trace})
            QA_store(index,case,rows[0],case_trace)
        trace.update(sources=all_sources, elapsed_seconds=round(time.monotonic()-started, 2))
        path = directory / f'package-{batch_index+1:03d}.json'
        path.write_text(json.dumps(trace, ensure_ascii=False, indent=2)); path.chmod(0o600)
    QA_map_reviews(batches, QA_review, workers, check_cancelled=check_cancelled, cancellation_scope=cancellation_scope)
    return results, len(reused)
