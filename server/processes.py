"""队列操作的协作取消；独立进程组同时终止运行器及其子进程。"""
import contextvars
import os
import signal
import subprocess
import time
from contextlib import contextmanager

_cancel = contextvars.ContextVar('testflow_cancel', default=None)


def current_cancellation_check():
    return _cancel.get()


def check_cancelled():
    check = _cancel.get()
    if check is not None and check():
        raise ValueError('操作已取消或任务版本已变化')


@contextmanager
def cancellation_scope(check):
    token = _cancel.set(check)
    try:
        yield
    finally:
        _cancel.reset(token)


def _kill_group(process):
    # 即使父进程已退出，也清理仍占用管道的后代。仅操作本次新建的进程组。
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.communicate()


def run(command, *, input=None, timeout=None, capture_output=False, check=False,
        on_tick=None, idle_timeout=None, activity_probe=None, **kwargs):
    """timeout限制总耗时；idle_timeout只限制连续无响应时长。

    activity_probe仅在观察到新响应时返回True；on_tick心跳不续期。
    """
    if idle_timeout is not None and (idle_timeout <= 0 or activity_probe is None):
        raise ValueError('无响应超时必须为正数且配置活动探针')
    cancelled = _cancel.get()
    if cancelled is None and on_tick is None and idle_timeout is None:
        return subprocess.run(command, input=input, timeout=timeout,
                              capture_output=capture_output, check=check, **kwargs)
    if cancelled and cancelled():
        raise ValueError('操作已取消或任务版本已变化')
    if capture_output:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if input is not None:
        kwargs['stdin'] = subprocess.PIPE
    started = time.monotonic()
    last_activity = started
    process = subprocess.Popen(command, start_new_session=True, **kwargs)
    try:
        first = True
        while True:
            if cancelled and cancelled():
                raise ValueError('操作已取消或任务版本已变化')
            if activity_probe is not None and activity_probe():
                last_activity = time.monotonic()
            if on_tick is not None: on_tick()
            now = time.monotonic()
            elapsed = now - started
            if timeout is not None and elapsed >= timeout:
                raise subprocess.TimeoutExpired(command, timeout)
            idle_elapsed = now - last_activity
            if idle_timeout is not None and idle_elapsed >= idle_timeout:
                raise subprocess.TimeoutExpired(command, idle_timeout)
            remaining = [.2]
            if timeout is not None: remaining.append(timeout-elapsed)
            if idle_timeout is not None: remaining.append(idle_timeout-idle_elapsed)
            interval = max(.001, min(remaining))
            try:
                stdout, stderr = process.communicate(input=input if first else None, timeout=interval)
                break
            except subprocess.TimeoutExpired:
                first = False
        if cancelled and cancelled():
            raise ValueError('操作已取消或任务版本已变化')
        result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        if check:
            result.check_returncode()
        return result
    except BaseException:
        _kill_group(process)
        raise
