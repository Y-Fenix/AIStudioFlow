"""只统计CLI事件元数据；不把需求、模型文本或推理写入操作日志。"""
import json
import time
import re

class StreamStats:
    def __init__(self,path):
        self.path=path;self.offset=0;self.received=0;self.assistant_chars=0
        self.errors=0;self.retries=0;self.last_event=None;self.last_activity=None
        self.progress_events=0;self.last_response=time.monotonic()
        self.pending=''
        self.failure=None;self.last_error_code=None;self.last_error_kind=None
    def sample(self):
        now=time.monotonic()
        size=self.path.stat().st_size if self.path.exists() else 0
        if size>self.offset:
            self.last_activity=now
            with self.path.open() as stream:
                stream.seek(self.offset)
                raw=stream.read(2000001)
                self.offset=stream.tell()
            self.pending+=raw
            lines=self.pending.split('\n');self.pending=lines.pop()
            if len(self.pending)>2000000:self.pending=''
            for line in lines:
                try:event=json.loads(line)
                except (ValueError,TypeError):continue
                if not isinstance(event,dict):continue
                self.received+=1
                kind=event.get('type')
                self.last_event=kind if kind in ('thread.started','turn.started','turn.completed','turn.failed','item.started','item.updated','item.completed','error') else 'other'
                # 重连报错和任意文件增长不能证明模型正在推进。
                if kind in ('thread.started','turn.started','turn.completed','item.started','item.updated','item.completed'):
                    self.progress_events+=1
                    self.last_response=now
                item=event.get('item') or {}
                if isinstance(item,dict) and item.get('type')=='agent_message' and isinstance(item.get('text'),str):
                    self.assistant_chars+=len(item['text'])
                if kind in ('error','turn.failed'):
                    self.errors+=1
                    error=event.get('error') or {}
                    message=error.get('message','') if isinstance(error,dict) else str(error)
                    message=str(event.get('message') or message)
                    status=re.search(r'(?i)(?:HTTP(?: status)?|status(?: code)?)\s*[:=]?\s*(\d{3})',message)
                    code=int(status.group(1)) if status else None
                    categories=[('unauthorized',r'(?i)unauthorized|authentication|invalid.*key'),
                                ('rate_limit',r'(?i)rate.limit|too many requests'),
                                ('transport',r'(?i)reconnect|stream.*disconnect|connection|timed? ?out|service unavailable|bad gateway|gateway timeout'),
                                ('model_unavailable',r'(?i)model.*(?:not found|not supported|unavailable)')]
                    category=next((name for name,pattern in categories if re.search(pattern,message)), 'upstream_error')
                    self.last_error_code=code;self.last_error_kind=category
                    # Only classified metadata leaves the stream; never error text or payload.
                    if kind=='turn.failed':self.failure={'code':code,'kind':category}
                    # 标记重连次数，但不保存消息全文。
                    if 'reconnect' in str(event.get('message','')).lower():self.retries+=1
        return {'events_received':self.received,'stream_bytes':size,'assistant_chars':self.assistant_chars,
                'progress_events':self.progress_events,'seconds_since_response':round(now-self.last_response,1),
                'error_events':self.errors,'upstream_error_code':self.last_error_code,'upstream_error_kind':self.last_error_kind,'retry_events':self.retries,'last_event':self.last_event,
                'seconds_since_activity':round(now-self.last_activity,1) if self.last_activity else None}
