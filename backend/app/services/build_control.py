"""Cooperative cancellation for the prototype's single-process API server.

A request-local context reaches every solver pass. The registry serialises the
last cancellation check with the database commit, so an acknowledged cancel can
never race past that commit. It is intentionally not a distributed job queue.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Event, RLock


class BuildCancelled(Exception):
    """The caller must roll back its request transaction."""


class BuildConflict(Exception):
    pass


@dataclass
class Operation:
    session_id: int
    operation_id: str
    started: bool = False
    state: str = "running"
    touched: float = field(default_factory=time.monotonic)
    cancelled: Event = field(default_factory=Event)


_current: ContextVar[Operation | None] = ContextVar("basket_build_operation", default=None)


def checkpoint() -> None:
    """Safe between expensive stages; synchronous solvers finish their current pass first."""
    operation = _current.get()
    if operation is not None and operation.cancelled.is_set():
        raise BuildCancelled()


class BuildRegistry:
    def __init__(self, *, retention_seconds: float = 20 * 60, max_entries: int = 1024):
        self.retention_seconds = retention_seconds
        self.max_entries = max_entries
        self._lock = RLock()
        self._operations: dict[tuple[int, str], Operation] = {}
        self._active: dict[int, str] = {}

    def _prune(self) -> None:
        cutoff = time.monotonic() - self.retention_seconds
        self._operations = {
            key: operation for key, operation in self._operations.items()
            if operation.touched >= cutoff or self._active.get(operation.session_id) == operation.operation_id
        }

    def _new(self, session_id: int, operation_id: str) -> Operation:
        if len(self._operations) >= self.max_entries:
            raise BuildConflict("Too many recent basket operations. Please retry shortly.")
        operation = Operation(session_id, operation_id)
        self._operations[(session_id, operation_id)] = operation
        return operation

    @contextmanager
    def track(self, session_id: int, operation_id: str) -> Iterator[Operation]:
        with self._lock:
            self._prune()
            operation = self._operations.get((session_id, operation_id))
            if operation and operation.started:
                raise BuildConflict("This build operation has already started. Use a new operation ID to retry.")
            # A cancellation may arrive before the build request reaches this worker.
            if operation is None or not operation.cancelled.is_set():
                if session_id in self._active:
                    raise BuildConflict("A basket build is already running for this shop. Wait for it or cancel it first.")
                operation = operation or self._new(session_id, operation_id)
                self._active[session_id] = operation_id
            operation.started = True
            operation.touched = time.monotonic()
        token = _current.set(operation)
        try:
            checkpoint()
            yield operation
        except BuildCancelled:
            with self._lock:
                operation.state = "cancelled"
            raise
        except BaseException:
            with self._lock:
                if operation.state != "committed":
                    operation.state = "failed"
            raise
        finally:
            _current.reset(token)
            with self._lock:
                operation.touched = time.monotonic()
                if self._active.get(session_id) == operation_id:
                    self._active.pop(session_id, None)

    def cancel(self, session_id: int, operation_id: str) -> dict:
        with self._lock:
            self._prune()
            operation = self._operations.get((session_id, operation_id))
            if operation and operation.state in {"committed", "cancelled", "failed"}:
                return {"status": "already_finished", "outcome": operation.state}
            operation = operation or self._new(session_id, operation_id)
            operation.cancelled.set()
            operation.state = "cancellation_requested"
            operation.touched = time.monotonic()
            return {"status": "cancellation_requested"}

    def commit(self, operation: Operation, save: Callable[[], None]) -> None:
        # Hold the same gate as cancel through commit. Cancellation either wins
        # before save, or observes committed; there is no third ambiguous window.
        with self._lock:
            if operation.cancelled.is_set():
                raise BuildCancelled()
            save()
            operation.state = "committed"
            operation.touched = time.monotonic()


builds = BuildRegistry()
