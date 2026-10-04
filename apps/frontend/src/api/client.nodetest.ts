/**
 * Runs with Node's built-in test runner and type stripping (no npm packages needed):
 *   node --test src/api/client.nodetest.ts
 * Named *.nodetest.ts so Vitest does not pick it up.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { ApiError, createClient, needsAction, type Run } from './client.ts';

interface Call {
  url: string;
  init: RequestInit;
}

function fakeFetch(status: number, body: unknown, calls: Call[]): typeof fetch {
  return (async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init: init ?? {} });
    return new Response(typeof body === 'string' ? body : JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json', 'X-Request-Id': 'req_hdr' },
    });
  }) as typeof fetch;
}

const RUN: Run = {
  run_id: 'run_0123456789abcdef',
  status: 'AWAITING_APPROVAL',
  intent: 'api_execution',
  query: 'Create a payment',
  environment: 'sandbox',
  message: 'Approval required',
  requested_by: 'alice',
  created_at: '2026-10-03T00:00:00Z',
  elapsed_s: 0.01,
  evidence: [],
  missing_fields: [],
  tool_calls: 3,
  pending_approval: {
    step_id: 'call',
    skill_id: 'api.call.write',
    action_hash: 'a'.repeat(64),
    environment: 'sandbox',
    summary: 'POST /v1/payments',
  },
  timeline: [],
};

test('sends bearer token, JSON body and encodes query parameters', async () => {
  const calls: Call[] = [];
  const client = createClient({
    baseUrl: 'http://api.local/',
    getToken: () => 'tok',
    fetchImpl: fakeFetch(201, RUN, calls),
  });
  const run = await client.createRun('Create a payment');
  assert.equal(run.run_id, RUN.run_id);
  assert.equal(calls[0].url, 'http://api.local/api/v1/runs');
  const headers = calls[0].init.headers as Record<string, string>;
  assert.equal(headers.Authorization, 'Bearer tok');
  assert.deepEqual(JSON.parse(String(calls[0].init.body)), {
    query: 'Create a payment',
    environment: 'sandbox',
  });
  assert.equal(calls[0].init.redirect, 'error');

  await createClient({ fetchImpl: fakeFetch(200, { results: [] }, calls) }).searchApis(
    'refund & cancel',
    3
  );
  assert.equal(calls[1].url, '/api/v1/apis/search?q=refund+%26+cancel&limit=3');
  assert.equal((calls[1].init.headers as Record<string, string>).Authorization, undefined);
});

test('maps platform errors to ApiError, including non-JSON bodies', async () => {
  const client = createClient({
    fetchImpl: fakeFetch(
      403,
      { code: 'ACCESS_DENIED', message: 'approver lacks approval:grant', requestId: 'req_1' },
      []
    ),
  });
  await assert.rejects(
    client.me(),
    (err: unknown) =>
      err instanceof ApiError &&
      err.status === 403 &&
      err.code === 'ACCESS_DENIED' &&
      err.requestId === 'req_1'
  );
  const broken = createClient({ fetchImpl: fakeFetch(502, '<html>bad gateway</html>', []) });
  await assert.rejects(
    broken.health(),
    (err: unknown) =>
      err instanceof ApiError && err.code === 'HTTP_502' && err.requestId === 'req_hdr'
  );
});

test('approve sends exactly the displayed hash and validates identifiers locally', async () => {
  const calls: Call[] = [];
  const client = createClient({
    fetchImpl: fakeFetch(200, { ...RUN, status: 'COMPLETED', pending_approval: null }, calls),
  });
  const done = await client.approveRun(RUN.run_id, 'a'.repeat(64));
  assert.equal(done.status, 'COMPLETED');
  assert.deepEqual(JSON.parse(String(calls[0].init.body)), { action_hash: 'a'.repeat(64) });
  assert.throws(() => client.approveRun('../admin', 'a'.repeat(64)), /invalid run id/);
  assert.throws(() => client.approveRun(RUN.run_id, 'not-a-hash'), /invalid action hash/);
  assert.equal(calls.length, 1);
});

test('needsAction', () => {
  assert.equal(needsAction(RUN), true);
  assert.equal(needsAction({ ...RUN, status: 'COMPLETED' }), false);
});
