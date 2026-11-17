"""Read-only project Agent capability, separate from single-shot text requests."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from server.ai_models import current_selection, defaults
from server.codex_model import CodexModel, current_diagnostic
from server.codex_stream import StreamStats
from server.model_output import parse_object
from server.processes import run as run_process, check_cancelled


class CodexAgent:
    def request_json(self, prompt, root, schema, *, selection=None, progress=None, audit_dir=None):
        selected = selection or current_selection() or defaults()
        if selected.get('source') == 'custom' and selected.get('protocol') != 'responses':
            raise ValueError('项目 Codex Agent 需要 Responses 协议；当前 Chat API 保持文字执行器，不暗换模型')
        executable = shutil.which('codex')
        if not executable:
            raise ValueError('未找到本机 Codex CLI，无法启动项目 Agent')
        project = Path(root).resolve()
        if not project.is_dir():
            raise ValueError('项目 Agent 工作目录不存在')
        model, effort = selected.get('model', 'gpt-6.1-sol'), selected.get('effort', 'high')
        # exec JSONL publishes completed messages, not every output token. Large
        # final reports can be actively streaming upstream while stdout is quiet.
        timeout = int(os.environ.get('TESTFLOW_AGENT_IDLE_TIMEOUT', '1800'))
        if effort not in (None, 'low', 'medium', 'high', 'xhigh') or not 30 <= timeout <= 1800:
            raise ValueError('项目 Agent 推理或超时配置无效')
        callback = progress or current_diagnostic()
        started = time.monotonic()
        check_cancelled()
        with tempfile.TemporaryDirectory(prefix='studioflow-project-agent-') as folder:
            directory = Path(folder)
            output, schema_path = directory / 'result.json', directory / 'schema.json'
            events_path, error_path = directory / 'events.jsonl', directory / 'stderr.log'
            schema_path.write_text(json.dumps(schema, ensure_ascii=False))
            schema_path.chmod(0o600)
            shell_home=directory/'shell-home'
            shell_home.mkdir(mode=0o700)
            command = [executable, 'exec', '--ignore-user-config', '--ephemeral',
                       '--disable', 'plugins', '--disable', 'remote_plugin', '--disable', 'apps',
                       '--skip-git-repo-check', '--sandbox', 'read-only', '-C', str(project),
                       '--color', 'never', '--json', '--output-schema', str(schema_path), '-o', str(output)]
            environment = os.environ.copy()
            if selected.get('source') == 'custom':
                # API keys only enter the child environment, never argv or progress.
                endpoint = selected['base_url'].rstrip('/')
                if endpoint.endswith('/responses'):
                    endpoint = endpoint[:-len('/responses')]
                environment['STUDIOFLOW_CODEX_AGENT_KEY'] = selected['api_key']
                configuration = {'model_provider': 'studioflow_runtime',
                    'model_providers.studioflow_runtime.name': 'StudioFlow configured API',
                    'model_providers.studioflow_runtime.base_url': endpoint,
                    'model_providers.studioflow_runtime.wire_api': 'responses',
                    'model_providers.studioflow_runtime.env_key': 'STUDIOFLOW_CODEX_AGENT_KEY',
                    'model_providers.studioflow_runtime.requires_openai_auth': False}
                connection = [part for key, value in configuration.items() for part in ('-c', key + '=' + json.dumps(value))]
            else:
                connection = CodexModel().connection_config()
            command.extend(connection + ['-c', 'model=' + json.dumps(model)])
            if effort is not None:
                command.extend(['-c', 'model_reasoning_effort=' + json.dumps(effort)])
            # Provider credentials are needed by Codex, never by its shell tools.
            command.extend(['-c', 'shell_environment_policy.inherit="none"',
                            '-c', 'shell_environment_policy.set.PATH=' + json.dumps(os.environ.get('PATH', '/usr/bin:/bin')),
                            '-c', 'shell_environment_policy.set.HOME=' + json.dumps(str(shell_home)),
                            '-c', 'shell_environment_policy.set.ZDOTDIR=' + json.dumps(str(shell_home)),
                            '-c', 'shell_environment_policy.set.LANG="en_US.UTF-8"', '-'])
            stats = StreamStats(events_path)
            last_tick = started
            marker = 0
            def emit(state):
                values = stats.sample()
                if callback:
                    callback({'state': state, 'transport': 'codex_cli', 'execution_engine': 'project_agent',
                        'requested_model': model, 'effort': effort, 'input_chars': len(prompt),
                        'elapsed_seconds': round(time.monotonic() - started, 2),
                        'timeout_kind': 'inactivity', 'idle_timeout_seconds': timeout, **values})
            def probe():
                nonlocal marker
                stats.sample()
                changed = stats.progress_events != marker
                marker = stats.progress_events
                if stats.failure:
                    raise ValueError('项目 Agent 模型服务失败：' + stats.failure['kind'])
                return changed
            def tick():
                nonlocal last_tick
                if time.monotonic() - last_tick >= 5:
                    last_tick = time.monotonic()
                    emit('running')
            emit('started')
            def preserve():
                if audit_dir is not None:
                    destination = Path(audit_dir)
                    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
                    for source in (events_path, output):
                        if source.is_file():
                            shutil.copyfile(source, destination / source.name)
                            (destination / source.name).chmod(0o600)
            try:
                with events_path.open('w') as stream, error_path.open('w') as error:
                    os.chmod(events_path, 0o600)
                    os.chmod(error_path, 0o600)
                    result = run_process(command, input=prompt, text=True, stdout=stream, stderr=error,
                        idle_timeout=timeout, activity_probe=probe, on_tick=tick, env=environment, check=False)
            except subprocess.TimeoutExpired:
                emit('idle_timeout')
                raise ValueError(f'项目 Agent 连续{timeout}秒无新活动，已停止当前工作包；已有结果不受影响') from None
            except OSError:
                emit('start_failed')
                raise ValueError('无法启动项目 Codex Agent') from None
            finally:
                preserve()
            check_cancelled()
            if result.returncode or not output.is_file():
                emit('cli_failed')
                raise ValueError('项目 Agent 未返回完整结果，请检查本机 Codex 登录和当前模型连接')
            if output.stat().st_size > 2000000:
                raise ValueError('项目 Agent 结果超过2MB限制')
            generated = parse_object(output.read_text(encoding='utf-8'))
            emit('completed')
            return generated
