import { describe, expect, it } from 'vitest';
import { createClient } from './client';
import { describeProgress, parseSseChunk, readEventStream } from './sse';

describe('parseSseChunk', () => {
  it('returns complete messages and keeps the partial remainder', () => {
    const { messages, rest } = parseSseChunk(
      'id: 1\nevent: intent\ndata: {"kind":"intent","detail":{"intent":"x"}}\n\n: keepalive\n\nid: 2\nevent: tool'
    );
    expect(messages).toHaveLength(1);
    expect(messages[0]).toMatchObject({ id: 1, event: 'intent' });
    expect(rest).toBe('id: 2\nevent: tool');
  });

  it('handles CRLF and multi-line data', () => {
    const { messages } = parseSseChunk('id: 3\r\nevent: x\r\ndata: a\r\ndata: b\r\n\r\n');
    expect(messages[0]).toMatchObject({ id: 3, data: 'a\nb' });
  });
});

describe('readEventStream', () => {
  const sse = (text: string, parts = 2) => {
    const bytes = new TextEncoder().encode(text);
    const size = Math.ceil(bytes.length / parts);
    return new Response(
      new ReadableStream({
        start(controller) {
          for (let i = 0; i < bytes.length; i += size) controller.enqueue(bytes.slice(i, i + size));
          controller.close();
        },
      }),
      { status: 200, headers: { 'Content-Type': 'text/event-stream' } }
    );
  };

  it('delivers events split across chunks, sends auth and Last-Event-ID', async () => {
    const seen: string[] = [];
    let headers: Record<string, string> = {};
    const fetchImpl = (async (_url: string, init: RequestInit) => {
      headers = init.headers as Record<string, string>;
      return sse(
        'id: 4\nevent: plan_step\ndata: {"kind":"plan_step","detail":{"skill_id":"api.search"}}\n\n' +
          'id: 5\nevent: status\ndata: {"status":"COMPLETED","message":"ok"}\n\n',
        5
      );
    }) as unknown as typeof fetch;
    const client = createClient({ getToken: () => 'tok', fetchImpl });
    await client.streamRun(
      'run_0123456789abcdef',
      (e) => seen.push(`${e.id}:${e.kind}:${describeProgress(e)}`),
      { lastEventId: 3 }
    );
    expect(seen).toEqual(['4:plan_step:Planned api.search', '5:status:null']);
    expect(headers.Authorization).toBe('Bearer tok');
    expect(headers['Last-Event-ID']).toBe('3');
  });

  it('fails clearly on a non-200 response', async () => {
    const fetchImpl = (async () =>
      new Response('nope', { status: 404 })) as unknown as typeof fetch;
    await expect(readEventStream('/x', {}, () => undefined, { fetchImpl })).rejects.toThrow(
      /HTTP 404/
    );
  });

  it('surfaces 429 Retry-After on ApiError', async () => {
    const fetchImpl = (async () =>
      new Response(JSON.stringify({ code: 'MODEL_BUSY', message: 'busy', requestId: 'r' }), {
        status: 429,
        headers: { 'Retry-After': '12' },
      })) as unknown as typeof fetch;
    await expect(createClient({ fetchImpl }).createRunAsync('hi')).rejects.toMatchObject({
      status: 429,
      retryAfterS: 12,
    });
  });
});
