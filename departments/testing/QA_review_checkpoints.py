"""Private, disposable per-case checkpoints. Callers still validate live evidence."""
import contextvars
import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path

QA_CHECKPOINT_ROOT = contextvars.ContextVar('QA_review_checkpoint', default=None)


@contextmanager
def QA_checkpoint_scope(folder):
    token = QA_CHECKPOINT_ROOT.set(Path(folder))
    try:
        yield
    finally:
        QA_CHECKPOINT_ROOT.reset(token)


def QA_checkpoint_path(inputs):
    root = QA_CHECKPOINT_ROOT.get()
    if root is None:
        return None
    signature = hashlib.sha256(json.dumps(inputs, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return root / (signature + '.json')


def QA_read_checkpoint(path):
    if path is None:
        return None
    try:
        if path.is_symlink() or path.stat().st_size > 8000000:
            return None
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def QA_write_checkpoint(path, value):
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name('.' + uuid.uuid4().hex + '.tmp')
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
