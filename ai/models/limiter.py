"""Model concurrency limiter with a bounded, tenant-fair queue (G4).

``mlx_lm.server`` handles one request at a time, so concurrent runs would otherwise pile
up inside the server and time out. ``LimitedProvider`` wraps any provider:

* at most ``concurrency`` model calls are in flight (default 1);
* waiters queue per tenant and are served round-robin across tenants, so one tenant's burst
  cannot starve another;
* a *new* run (its first, ``intent`` call) is refused with :class:`ModelBusyError` when the
  queue is full, which the API maps to ``429`` + ``Retry-After``. Calls of runs that were
  already admitted are never dropped for queue size;
* how long a call waited is reported through :func:`ai.models.observe.record_queue_wait`, so
  the orchestrator can exclude queue time from the run's time budget and record it.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict, deque

from ai.models.base import ModelProvider, ModelRequest, ModelResponse, ModelUnavailableError
from ai.models.observe import current_tenant, record_queue_wait


class ModelBusyError(ModelUnavailableError):
    """Every model slot is busy and the queue is full; retry later."""

    def __init__(self, retry_after_s: int, queued: int) -> None:
        super().__init__(f"the model is busy ({queued} requests queued); retry in {retry_after_s}s")
        self.retry_after_s = retry_after_s
        self.queued = queued


class FairLimiter:
    def __init__(
        self, concurrency: int = 1, max_queue: int = 8, *, typical_call_s: float = 8.0
    ) -> None:
        if concurrency < 1 or max_queue < 0:
            raise ValueError("concurrency must be >= 1 and max_queue >= 0")
        self.concurrency, self.max_queue = concurrency, max_queue
        self._typical_call_s = typical_call_s
        self._active = 0
        self._queues: OrderedDict[str, deque[asyncio.Future[None]]] = OrderedDict()

    @property
    def queued(self) -> int:
        return sum(len(q) for q in self._queues.values())

    @property
    def active(self) -> int:
        return self._active

    def retry_after_s(self) -> int:
        return max(1, round((self.queued + 1) * self._typical_call_s / self.concurrency))

    def check_admission(self) -> None:
        """Raise :class:`ModelBusyError` if a new run would be refused right now."""
        if self._active >= self.concurrency and self.queued >= self.max_queue:
            raise ModelBusyError(self.retry_after_s(), self.queued)

    async def acquire(self, tenant: str, *, admit: bool) -> float:
        """Wait for a slot; returns seconds waited. ``admit`` applies the queue bound."""
        if self._active < self.concurrency and not self.queued:
            self._active += 1
            return 0.0
        if admit and self.queued >= self.max_queue:
            raise ModelBusyError(self.retry_after_s(), self.queued)
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._queues.setdefault(tenant, deque()).append(future)
        started = time.perf_counter()
        try:
            await future
        except asyncio.CancelledError:
            self._forget(tenant, future)
            if future.done() and not future.cancelled():
                self.release()  # the slot was handed to us just as we were cancelled
            raise
        return time.perf_counter() - started

    def _forget(self, tenant: str, future: asyncio.Future[None]) -> None:
        queue = self._queues.get(tenant)
        if queue is not None:
            try:
                queue.remove(future)
            except ValueError:
                pass
            if not queue:
                del self._queues[tenant]

    def release(self) -> None:
        self._active -= 1
        # Round-robin: take the oldest waiter of the first tenant, then rotate that tenant
        # to the back so the next release serves someone else.
        while self._queues and self._active < self.concurrency:
            tenant, queue = next(iter(self._queues.items()))
            future = queue.popleft()
            if not queue:
                del self._queues[tenant]
            else:
                self._queues.move_to_end(tenant)
            if future.cancelled():
                continue
            self._active += 1
            future.set_result(None)


class LimitedProvider:
    """A ``ModelProvider`` that takes a slot from the limiter around each call."""

    def __init__(self, inner: ModelProvider, limiter: FairLimiter) -> None:
        self.inner, self.limiter = inner, limiter
        self.name, self.model = inner.name, inner.model

    async def generate(self, request: ModelRequest) -> ModelResponse:
        waited = await self.limiter.acquire(current_tenant(), admit=request.task == "intent")
        record_queue_wait(waited)
        try:
            return await self.inner.generate(request)
        finally:
            self.limiter.release()
