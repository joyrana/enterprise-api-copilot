/**
 * Minimal Server-Sent Events reader over fetch (EventSource cannot send an Authorization
 * header). Pure parsing lives in `parseSseChunk` so it can be tested without a network.
 */

export interface SseMessage {
  id: number | null;
  event: string;
  data: string;
}

/** Splits a text buffer into complete messages; returns the unconsumed remainder. */
export function parseSseChunk(buffer: string): { messages: SseMessage[]; rest: string } {
  const messages: SseMessage[] = [];
  const normalised = buffer.replace(/\r\n/g, '\n');
  const blocks = normalised.split('\n\n');
  const rest = blocks.pop() ?? '';
  for (const block of blocks) {
    let id: number | null = null;
    let event = 'message';
    const data: string[] = [];
    for (const line of block.split('\n')) {
      if (line.startsWith(':')) continue; // comment / keepalive
      const at = line.indexOf(':');
      const field = at === -1 ? line : line.slice(0, at);
      const value = at === -1 ? '' : line.slice(at + 1).replace(/^ /, '');
      if (field === 'id') id = Number.parseInt(value, 10);
      else if (field === 'event') event = value;
      else if (field === 'data') data.push(value);
    }
    if (data.length > 0 || event !== 'message') {
      messages.push({ id: Number.isNaN(id) ? null : id, event, data: data.join('\n') });
    }
  }
  return { messages, rest };
}

export interface RunProgressEvent {
  /** timeline event kind, or 'status' for the final message */
  kind: string;
  detail: Record<string, unknown>;
  id: number | null;
}

/** Human-readable line for a progress event, or null for events not worth showing. */
export function describeProgress(event: RunProgressEvent): string | null {
  const d = event.detail;
  switch (event.kind) {
    case 'intent':
      return `Understood the request as ${String(d.intent ?? 'unknown')}`;
    case 'skills_resolved':
      return `Allowed skills: ${((d.skills as string[] | undefined) ?? []).join(', ')}`;
    case 'plan_step':
      return `Planned ${String(d.skill_id)}${d.thought ? ` — ${String(d.thought)}` : ''}`;
    case 'plan_rejected':
      return `Refused a step (${String(d.reason ?? 'not allowed')})`;
    case 'tool_call':
      return `${d.ok ? 'Ran' : 'Paused/failed'} ${String(d.skill_id)}`;
    case 'clarified':
      return 'Continued with your answer';
    case 'ui':
      return 'Prepared the reply';
    case 'status':
      return null;
    default:
      return null;
  }
}

/**
 * Follows `GET {url}` as an event stream until the server closes it. Reconnects are the
 * caller's job (pass `lastEventId` to resume).
 */
export async function readEventStream(
  url: string,
  headers: Record<string, string>,
  onEvent: (event: RunProgressEvent) => void,
  options: { fetchImpl?: typeof fetch; signal?: AbortSignal; lastEventId?: number } = {}
): Promise<void> {
  const doFetch = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  const response = await doFetch(url, {
    headers: {
      Accept: 'text/event-stream',
      ...headers,
      ...(options.lastEventId ? { 'Last-Event-ID': String(options.lastEventId) } : {}),
    },
    signal: options.signal,
    redirect: 'error',
  });
  if (!response.ok || !response.body) {
    throw new Error(`event stream failed: HTTP ${response.status}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { messages, rest } = parseSseChunk(buffer);
    buffer = rest;
    for (const message of messages) {
      let parsed: Record<string, unknown> = {};
      try {
        parsed = JSON.parse(message.data) as Record<string, unknown>;
      } catch {
        continue;
      }
      const detail = (parsed.detail as Record<string, unknown> | undefined) ?? parsed;
      onEvent({ kind: message.event, detail, id: message.id });
    }
  }
}
