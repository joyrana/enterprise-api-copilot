"""G4: model concurrency limiter, fair queuing, async runs and the event stream."""

from __future__ import annotations

import asyncio
import json

import pytest

from ai.agent.contracts import RunStatus
from ai.agent.orchestrator import InMemoryCheckpointStore, Orchestrator
from ai.api.runs import RunNotFoundError, RunService
from ai.api.sse import _frames, parse_last_event_id
from ai.models.base import ModelRequest, ModelResponse, ScriptedModelProvider
from ai.models.limiter import FairLimiter, LimitedProvider, ModelBusyError
from ai.models.observe import current_tenant
from tests.support import build_harness
from tests.unit.test_llm_agent import DEV, FINISH, call, intent, reply

GINA = DEV.model_copy(update={"subject": "gina", "tenant_id": "globex"})


async def test_limiter_serves_tenants_round_robin() -> None:
    limiter = FairLimiter(concurrency=1, max_queue=10)
    await limiter.acquire("a", admit=True)  # holds the only slot
    order: list[str] = []

    async def waiter(tenant: str, label: str) -> None:
        await limiter.acquire(tenant, admit=True)
        order.append(label)
        limiter.release()

    tasks = [
        asyncio.create_task(waiter("a", "a1")),
        asyncio.create_task(waiter("a", "a2")),
        asyncio.create_task(waiter("a", "a3")),
        asyncio.create_task(waiter("b", "b1")),
    ]
    await asyncio.sleep(0)
    assert limiter.queued == 4
    limiter.release()
    await asyncio.gather(*tasks)
    # A burst from tenant a does not starve tenant b: b is served second, not last.
    assert order == ["a1", "b1", "a2", "a3"]
    assert limiter.active == 0 and limiter.queued == 0


async def test_new_runs_are_refused_when_the_queue_is_full_but_admitted_runs_wait() -> None:
    limiter = FairLimiter(concurrency=1, max_queue=1, typical_call_s=10)
    await limiter.acquire("a", admit=True)
    queued = asyncio.create_task(limiter.acquire("a", admit=True))
    await asyncio.sleep(0)
    with pytest.raises(ModelBusyError) as busy:
        await limiter.acquire("b", admit=True)
    assert busy.value.retry_after_s >= 10 and busy.value.queued == 1
    with pytest.raises(ModelBusyError):
        limiter.check_admission()
    mid_run = asyncio.create_task(limiter.acquire("b", admit=False))  # already admitted
    await asyncio.sleep(0)
    assert limiter.queued == 2
    limiter.release()
    await queued
    limiter.release()
    await mid_run
    limiter.release()


async def test_cancelled_waiters_do_not_leak_slots() -> None:
    limiter = FairLimiter(concurrency=1, max_queue=5)
    await limiter.acquire("a", admit=True)
    waiting = asyncio.create_task(limiter.acquire("a", admit=True))
    await asyncio.sleep(0)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    limiter.release()
    assert limiter.active == 0 and limiter.queued == 0
    assert await limiter.acquire("a", admit=True) == 0.0


class Slow:
    """Scripted outputs with a delay per call, to make runs overlap."""

    name, model = "slow", "slow-1"

    def __init__(self, outputs: list[str], delay: float) -> None:
        # One script per tenant: interleaved runs must not consume each other's outputs.
        self.scripts: dict[str, ScriptedModelProvider] = {}
        self.outputs, self.delay = outputs, delay

    async def generate(self, request: ModelRequest) -> ModelResponse:
        await asyncio.sleep(self.delay)
        script = self.scripts.setdefault(current_tenant(), ScriptedModelProvider(self.outputs))
        return await script.generate(request)


def _discovery_outputs() -> list[str]:
    return [intent("api_discovery"), call("api.search", query="x"), FINISH, reply("ok")]


async def test_two_concurrent_runs_complete_and_queue_wait_is_recorded() -> None:
    h = build_harness()
    llm = LimitedProvider(Slow(_discovery_outputs(), 0.05), FairLimiter(concurrency=1, max_queue=4))
    orchestrator = Orchestrator(h.services.runtime, llm=llm)
    first, second = await asyncio.gather(
        orchestrator.run("find an api", principal=DEV, environment="sandbox"),
        orchestrator.run("find an api", principal=GINA, environment="sandbox"),
    )
    assert first.status is RunStatus.COMPLETED and second.status is RunStatus.COMPLETED
    waits = sorted(r.model_usage.queue_wait_s for r in (first, second) if r.model_usage)
    assert waits[0] >= 0 and waits[1] > 0, "the run that queued recorded its wait"
    waited = next(r for r in (first, second) if r.model_usage and r.model_usage.queue_wait_s > 0)
    # Queue wait is excluded from the run's own elapsed time.
    assert waited.elapsed_s < (waited.model_usage.queue_wait_s if waited.model_usage else 0) + 0.5
    assert any(e.kind == "model_call" for e in waited.events)


async def test_second_run_gets_busy_when_no_queue_is_allowed() -> None:
    h = build_harness()
    llm = LimitedProvider(Slow(_discovery_outputs(), 0.1), FairLimiter(1, max_queue=0))
    orchestrator = Orchestrator(h.services.runtime, llm=llm)
    results = await asyncio.gather(
        orchestrator.run("find an api", principal=DEV, environment="sandbox"),
        orchestrator.run("find an api", principal=GINA, environment="sandbox"),
        return_exceptions=True,
    )
    runs = [r for r in results if not isinstance(r, BaseException)]
    busy = [r for r in results if isinstance(r, ModelBusyError)]
    assert len(runs) == 1 and len(busy) == 1 and runs[0].status is RunStatus.COMPLETED
    assert busy[0].retry_after_s >= 1


class Gate:
    """Blocks every model call until released, so a run can be observed mid-flight."""

    name, model = "gate", "gate-1"

    def __init__(self, outputs: list[str]) -> None:
        self.inner = ScriptedModelProvider(outputs)
        self.open = asyncio.Event()

    async def generate(self, request: ModelRequest) -> ModelResponse:
        await self.open.wait()
        return await self.inner.generate(request)


async def test_async_run_is_visible_while_running_and_streams_its_events() -> None:
    h = build_harness()
    gate = Gate(_discovery_outputs())
    store = InMemoryCheckpointStore()
    runs = RunService(Orchestrator(h.services.runtime, llm=gate, checkpoints=store), store)
    started = await runs.start_async(DEV, "find an api", "sandbox")
    assert started.status is RunStatus.RUNNING and started.run_id.startswith("run_")
    assert runs.get(started.run_id, "acme").status is RunStatus.RUNNING
    with pytest.raises(RunNotFoundError):
        runs.get(started.run_id, "globex")  # another tenant cannot even see it running

    frames: list[str] = []

    async def follow(after: int = 0) -> None:
        async for frame in _frames(lambda: runs.get(started.run_id, "acme"), after, poll_s=0.01):
            frames.append(frame)

    follower = asyncio.create_task(follow())
    await asyncio.sleep(0.05)
    assert [f for f in frames if "event: intent" in f] == [], "no model output yet"
    gate.open.set()
    await asyncio.wait_for(follower, 10)
    names = [
        line.split(": ", 1)[1]
        for f in frames
        for line in f.splitlines()
        if line.startswith("event: ")
    ]
    assert names[0] == "created" and "intent" in names and "tool_call" in names
    assert names[-1] == "status"
    # The stream must not close before the reply and UI exist (status turns COMPLETED earlier).
    assert names.index("ui") < names.index("settled") < names.index("status")
    final = json.loads(frames[-1].split("data: ", 1)[1])
    assert final["status"] == "COMPLETED" and final["run_id"] == started.run_id

    # Resuming after the 3rd event replays only what came later; ids are positions.
    resumed: list[str] = []
    async for frame in _frames(lambda: runs.get(started.run_id, "acme"), 3, poll_s=0.01):
        resumed.append(frame)
    assert resumed[0].startswith("id: 4\n") and resumed[-1] == frames[-1]
    assert len(resumed) == len(frames) - 3


async def test_async_run_that_hits_a_busy_model_ends_failed_not_stuck() -> None:
    h = build_harness()
    limiter = FairLimiter(concurrency=1, max_queue=0)
    await limiter.acquire("other", admit=True)  # the model is occupied
    store = InMemoryCheckpointStore()
    runs = RunService(
        Orchestrator(
            h.services.runtime,
            llm=LimitedProvider(ScriptedModelProvider(_discovery_outputs()), limiter),
            checkpoints=store,
        ),
        store,
    )
    with pytest.raises(ModelBusyError):  # refused before any run exists
        await runs.start_async(DEV, "find an api", "sandbox")
    assert store.list_runs("acme") == []


def test_last_event_id_is_parsed_defensively() -> None:
    assert parse_last_event_id("7") == 7
    assert parse_last_event_id("-3") == 0 and parse_last_event_id("abc") == 0
    assert parse_last_event_id(None) == 0


class GateResponder:
    """Answers intent/plan at once but holds the final reply until released."""

    name, model = "gate", "gate-1"

    def __init__(self, outputs: list[str]) -> None:
        self.inner = ScriptedModelProvider(outputs)
        self.open = asyncio.Event()

    async def generate(self, request: ModelRequest) -> ModelResponse:
        if request.task == "respond":
            await self.open.wait()
        return await self.inner.generate(request)


async def test_the_stream_does_not_close_while_the_reply_is_still_being_written() -> None:
    h = build_harness()
    llm = GateResponder(
        [
            intent("api_discovery"),
            call("api.search", query="x"),
            FINISH,
            reply("ok", ("operation_list", "search")),
        ]
    )
    store = InMemoryCheckpointStore()
    runs = RunService(Orchestrator(h.services.runtime, llm=llm, checkpoints=store), store)
    started = await runs.start_async(DEV, "find an api", "sandbox")
    for _ in range(300):  # wait until the run reached COMPLETED but is still responding
        state = runs.get(started.run_id, "acme")
        if state.status is RunStatus.COMPLETED:
            break
        await asyncio.sleep(0.01)
    assert state.status is RunStatus.COMPLETED and state.settled is False

    frames: list[str] = []

    async def follow() -> None:
        async for frame in _frames(lambda: runs.get(started.run_id, "acme"), 0, poll_s=0.01):
            frames.append(frame)

    follower = asyncio.create_task(follow())
    await asyncio.sleep(0.1)
    assert not follower.done() and not any("event: status" in f for f in frames)
    llm.open.set()
    await asyncio.wait_for(follower, 10)
    assert "event: ui" in "".join(frames) and frames[-1].startswith("id: ")
    assert "event: status" in frames[-1]
    final = runs.get(started.run_id, "acme")
    assert final.settled is True and final.ui, "the reply and UI exist when the stream ends"
