"""Server-Sent Events for run progress (G4).

``stream_run`` follows a run through the checkpoint store, so it works for runs executing in
this process (async mode) and for runs resumed elsewhere. Each timeline event becomes one SSE
message with ``id`` = its 1-based position, which makes the stream resumable with
``Last-Event-ID``. Payloads are the same redacted ``TimelineEvent`` shape as ``RunView``; a
final ``status`` event carries the run status and message, then the stream closes. Pauses
(approval, clarification) also close the stream: the client reconnects after it acts.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable

from starlette.responses import StreamingResponse

from ai.agent.contracts import RunState, RunStatus
from skills.runtime.redaction import redact, redact_text

POLL_S = 0.15
HEARTBEAT_S = 15.0
MAX_STREAM_S = 600.0


def _message(event_id: int, name: str, data: object) -> str:
    return f"id: {event_id}\nevent: {name}\ndata: {json.dumps(data, default=str)}\n\n"


def parse_last_event_id(value: str | None) -> int:
    try:
        return max(0, int(value or 0))
    except ValueError:
        return 0


_END_MARKERS = ("settled", "run_error")


def _settled(state: RunState) -> bool:
    """The run is no longer changing: not RUNNING, and its last segment wrote its end marker.

    Runs stored before the marker existed have none anywhere; for those a non-RUNNING status
    is final.
    """
    if state.status is RunStatus.RUNNING:
        return False
    if not any(e.kind in _END_MARKERS for e in state.events):
        return True
    return bool(state.events) and state.events[-1].kind in _END_MARKERS


async def _frames(load: Callable[[], RunState], after: int, *, poll_s: float) -> AsyncIterator[str]:
    sent = after
    waited = 0.0
    quiet = 0.0
    while waited < MAX_STREAM_S:
        state = load()
        events = state.events
        for index in range(sent, len(events)):
            event = events[index]
            yield _message(
                index + 1, event.kind, {"kind": event.kind, "detail": redact(event.detail)}
            )
            sent = index + 1
            quiet = 0.0
        if _settled(state):
            yield _message(
                len(events) + 1,
                "status",
                {
                    "status": state.status.value,
                    "message": redact_text(state.message),
                    "run_id": state.run_id,
                },
            )
            return
        await asyncio.sleep(poll_s)
        waited += poll_s
        quiet += poll_s
        if quiet >= HEARTBEAT_S:
            quiet = 0.0
            yield ": keepalive\n\n"
    yield _message(sent + 1, "timeout", {"message": "stream time limit reached; reconnect"})


def stream_run(
    load: Callable[[], RunState], *, last_event_id: str | None, poll_s: float = POLL_S
) -> StreamingResponse:
    """``load`` must raise ``RunNotFoundError`` for missing/foreign runs (checked up front)."""
    load()  # 404 before any bytes are sent
    return StreamingResponse(
        _frames(load, parse_last_event_id(last_event_id), poll_s=poll_s),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
