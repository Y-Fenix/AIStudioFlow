"""Check history accounting, not the truth of evidence or completeness of review."""
import argparse
import json
from pathlib import Path


PENDING = {'pending_review', 'needs_revalidation'}
CLOSED = {'fixed', 'false_positive', 'not_applicable'}


def validate(current, previous):
    errors = []
    required = {}
    for source, report in previous.items():
        for assertion in report.get('assertions', []):
            if assertion.get('status') in {'issue', 'risk'}:
                required[(source, assertion['id'])] = assertion['status']
        # Pending history must survive even when it was never a current assertion.
        for row in report.get('history_tracking', []):
            if row.get('disposition') in PENDING:
                required.setdefault((row['source_report'], row['source_id']), None)

    assertions = {}
    for assertion in current.get('assertions', []):
        aid = assertion.get('id')
        if not aid or aid in assertions:
            errors.append('Missing or duplicate current assertion ID: ' + str(aid))
        assertions[aid] = assertion
    rows = {}
    for row in current.get('history_tracking', []):
        key = (row.get('source_report'), row.get('source_id'))
        if key in rows:
            errors.append('Duplicate history row: ' + str(key))
        rows[key] = row
        state = row.get('disposition')
        if state not in PENDING | CLOSED | {'confirmed'}:
            errors.append('Invalid disposition: ' + str(key))
        if state in CLOSED:
            if not row.get('reason') or not row.get('evidence'):
                errors.append('Closure needs reason and evidence: ' + str(key))
        if state == 'confirmed':
            assertion = assertions.get(row.get('current_id'), {})
            if assertion.get('status') not in {'issue', 'risk'}:
                errors.append('Confirmed history needs current issue/risk: ' + str(key))
            old_status = required.get(key)
            if old_status and old_status != assertion.get('status'):
                if not row.get('reason') or not row.get('evidence'):
                    errors.append('Reclassification needs reason and evidence: ' + str(key))
    for key in required:
        if key not in rows:
            errors.append('Unaccounted historical issue/risk: ' + str(key))
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--current', required=True)
    parser.add_argument('--previous', action='append', default=[])
    args = parser.parse_args()
    try:
        current = json.loads(Path(args.current).read_text())
        previous = {str(Path(p).resolve()): json.loads(Path(p).read_text())
                    for p in args.previous}
        errors = validate(current, previous)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        errors = ['Invalid input: ' + str(exc)]
    print(json.dumps({'passed': not errors, 'errors': errors,
                      'boundary': 'Checks supplied history accounting only; does not validate evidence or discover omitted reports.'},
                     ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
