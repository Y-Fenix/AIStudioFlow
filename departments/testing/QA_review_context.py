"""Transient retrieval hints; never share model conclusions or infer business groups."""
import copy


QA_RETRIEVAL_VERSION = 'exact-point-evidence-v1'
QA_SEED_BYTES = 120000


def QA_evidence_keys(case):
    keys = []
    module = case.get('module')
    if isinstance(module, str) and module.strip():
        keys.append(('module', module.strip()))
    points = case.get('point_ids', [])
    if isinstance(points, list):
        for point in points:
            if isinstance(point, str) and point.strip() and ('point', point) not in keys:
                keys.append(('point', point))
    return keys


def QA_primary_affinity(case):
    keys = QA_evidence_keys(case)
    return keys[0] if keys else None


def QA_merge_source_windows(previous, addition):
    """Only called with excerpts already checked against the same live source hash."""
    old, new = previous.splitlines(keepends=True), addition.splitlines(keepends=True)
    result = old + ['\n'] * max(0, len(new) - len(old))
    for index, line in enumerate(new):
        if line.strip():
            result[index] = line
    return ''.join(result)


def QA_compact_source_search(requests, sources):
    """Keep full trace outside this request view. Removed text is exactly recoverable."""
    compact = copy.deepcopy(requests)
    lines = {name: content.splitlines() for name, content in sources.items()}
    for request in compact:
        for result in request.get('search', []):
            for hit in result.get('hits', []):
                line, text = hit.get('line'), hit.get('text')
                source = lines.get(hit.get('file'), [])
                if type(line) is int and 0 < line <= len(source) and isinstance(text, str) and source[line-1][:600] == text:
                    del hit['text']
                    hit['text_in_sources'] = True
    return compact
