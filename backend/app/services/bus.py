"""In-process event bus feeding the SSE stream. Pipeline threads publish; the async SSE
endpoint waits for new events. Events carry IDs and stage names only, never content."""

import threading
from collections import deque
from typing import Any


class Bus:
    def __init__(self, keep: int = 1000) -> None:
        self._cond = threading.Condition()
        self._events: deque[tuple[int, dict[str, Any]]] = deque(maxlen=keep)
        self._seq = 0

    @property
    def seq(self) -> int:
        return self._seq

    def publish(self, type_: str, **data: Any) -> None:
        with self._cond:
            self._seq += 1
            self._events.append((self._seq, {"type": type_, **data}))
            self._cond.notify_all()

    def wait(self, after: int, timeout: float) -> list[tuple[int, dict[str, Any]]]:
        with self._cond:
            self._cond.wait_for(lambda: self._seq > after, timeout=timeout)
            return [e for e in self._events if e[0] > after]


bus = Bus()
