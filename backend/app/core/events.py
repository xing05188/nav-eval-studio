"""进程内事件总线。

任务执行线程 / 协程通过 publish 推送进度、资源采样与日志；
SSE 接口通过 subscribe 获取队列，逐个取出并以 text/event-stream 下发。
单机单进程模型下无需 Redis，保持零外部依赖。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any


class EventBus:
    def __init__(self, queue_size: int = 256) -> None:
        self._channels: dict[int, set[asyncio.Queue]] = defaultdict(set)
        self._queue_size = queue_size
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """绑定主事件循环，供工作线程安全投递。"""
        self._loop = loop

    def subscribe(self, task_id: int) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_size)
        self._channels[task_id].add(queue)
        return queue

    def unsubscribe(self, task_id: int, queue: asyncio.Queue) -> None:
        channel = self._channels.get(task_id)
        if channel:
            channel.discard(queue)
            if not channel:
                self._channels.pop(task_id, None)

    def publish(self, task_id: int, event: str, data: dict[str, Any]) -> None:
        message = {"event": event, "data": data}
        for queue in list(self._channels.get(task_id, ())):
            self._put(queue, message)

    def publish_threadsafe(self, task_id: int, event: str, data: dict[str, Any]) -> None:
        """从子线程投递，转交主循环执行。"""
        if self._loop is None or not self._loop.is_running():
            self.publish(task_id, event, data)
            return
        self._loop.call_soon_threadsafe(self.publish, task_id, event, data)

    def _put(self, queue: asyncio.Queue, message: dict[str, Any]) -> None:
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            # 消费端过慢时丢弃最旧事件，保证生产者不被阻塞
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                pass


BUS = EventBus()
