"""Bounded independent reviews; preserves caller contexts and cooperates with cancellation."""
import contextvars
import os
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait


def QA_review_workers():
    try:
        workers = int(os.environ.get('TESTFLOW_STATIC_WORKERS', '3'))
    except (TypeError, ValueError):
        raise ValueError('静态审查并发数必须为1至3') from None
    if not 1 <= workers <= 3:
        raise ValueError('静态审查并发数必须为1至3')
    return workers


def QA_map_reviews(items, review, workers, *, check_cancelled, cancellation_scope, affinity_key=None):
    """Return in input order; never queue more than workers uncompleted reviews."""
    aborted = threading.Event()
    results = [None] * len(items)
    pending = {}
    remaining = list(range(len(items)))
    keys = [affinity_key(item) if affinity_key else None for item in items]
    active_keys = set()

    def QA_one(index):
        with cancellation_scope(aborted.is_set):
            check_cancelled()
            return review(index, items[index])

    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='testflow-static')
    try:
        while remaining or pending:
            check_cancelled()
            while remaining and len(pending) < workers:
                next_index = next((i for i in remaining if keys[i] is None or keys[i] not in active_keys), None)
                if next_index is None:
                    break
                remaining.remove(next_index)
                if keys[next_index] is not None:
                    active_keys.add(keys[next_index])
                context = contextvars.copy_context()
                pending[pool.submit(context.run, QA_one, next_index)] = next_index
            done, _ = wait(pending, return_when=FIRST_COMPLETED, timeout=.2)
            # Inspect all completed work before dispatching replacements. Any failure
            # aborts this task; successful checkpoints already written remain reusable.
            for future in done:
                index = pending.pop(future)
                results[index] = future.result()
                active_keys.discard(keys[index])
    except BaseException:
        aborted.set()
        for future in pending:
            future.cancel()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    return results
