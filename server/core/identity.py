"""Per-request identity; never accept a user id from query parameters or headers."""
from contextvars import ContextVar

current_user = ContextVar('studioflow_user', default='local')


def user_id(value=None):
    return current_user.get() if value is None else value
