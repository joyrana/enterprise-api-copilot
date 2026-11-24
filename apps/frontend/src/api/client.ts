/**
 * Typed client for the platform API (contracts/openapi/platform-api.yaml).
 *
 * The web app talks only to the platform (same origin; Vite proxies /api in dev).
 * Errors surface as ApiError with the platform's error body, so the UI can show what
 * actually happened instead of a fabricated result.
 */

import { readEventStream, type RunProgressEvent } from './sse.ts';

export type { RunProgressEvent } from './sse.ts';

export type RunStatus =
  'RUNNING' | 'AWAITING_APPROVAL' | 'NEEDS_CLARIFICATION' | 'COMPLETED' | 'REJECTED' | 'FAILED';

export interface PendingApproval {
  step_id: string;
  skill_id: string;
  action_hash: string;
  environment: string;
  summary: string;
}

export interface TimelineEvent {
  kind: string;
  detail?: Record<string, unknown>;
}

/** Names in the server's component registry (ai/agent/ui.py). */
export type UIComponentName =
  | 'operation_list'
  | 'operation_detail'
  | 'code_snippets'
  | 'api_response'
  | 'doc_sources'
  | 'jwt_report'
  | 'run_trace'
  | 'approval_request'
  | 'clarification';

/** A component the agent chose for its reply; props are built server-side from step output. */
export interface UIComponent {
  id: string;
  component: UIComponentName | string;
  source: string | null;
  props: Record<string, unknown>;
}

export interface ModelUsage {
  provider: string;
  model: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  /** Model calls that failed; any failure ends the run as FAILED (no rules fallback). */
  failures: number;
}

export interface Run {
  run_id: string;
  status: RunStatus;
  intent: string | null;
  query: string;
  environment: string;
  message: string;
  requested_by: string;
  created_at: string;
  elapsed_s: number;
  evidence: string[];
  missing_fields: string[];
  tool_calls: number;
  pending_approval: PendingApproval | null;
  timeline: TimelineEvent[];
  /** agentic = LLM-driven run; deterministic = rules/templates (only when no model is configured). */
  mode?: 'agentic' | 'deterministic';
  ui?: UIComponent[];
  model?: ModelUsage | null;
  conversation_id?: string | null;
}

export interface Conversation {
  conversation_id: string;
  created_at: string;
  created_by?: string;
  runs: Run[];
}

export interface Me {
  subject: string;
  tenant_id: string;
  roles: string[];
}

export interface Skill {
  id: string;
  name: string;
  version: string;
  description: string;
  side_effect: 'NONE' | 'READ' | 'WRITE' | 'DESTRUCTIVE';
  required_permissions: string[];
  requires_approval: boolean;
}

export interface ApiSearchHit {
  operation_id: string;
  api: string;
  method: string;
  path: string;
  summary: string;
  scopes: string[];
  score: number;
  rank: number;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  requestId: string;
  path?: string;
  timestamp?: string;
}

export class ApiError extends Error {
  readonly status: number;
  /** Seconds to wait before retrying (429 MODEL_BUSY). */
  readonly retryAfterS: number | null;
  readonly code: string;
  readonly requestId: string;

  constructor(status: number, body: ApiErrorBody, retryAfterS: number | null = null) {
    super(`${body.code}: ${body.message}`);
    this.name = 'ApiError';
    this.status = status;
    this.code = body.code;
    this.requestId = body.requestId;
    this.retryAfterS = retryAfterS;
  }
}

export interface ClientOptions {
  /** Base URL of the platform; '' means same origin. */
  baseUrl?: string;
  /** Returns the current bearer token, or null when signed out. */
  getToken?: () => string | null;
  fetchImpl?: typeof fetch;
}

const ACTION_HASH = /^[0-9a-f]{64}$/;
const RUN_ID = /^run_[0-9a-f]{16}$/;
const CONVERSATION_ID = /^conv_[0-9a-f]{16}$/;

function assertRunId(runId: string): void {
  if (!RUN_ID.test(runId)) {
    throw new Error(`invalid run id: ${runId}`);
  }
}

export function createClient(options: ClientOptions = {}) {
  const baseUrl = (options.baseUrl ?? '').replace(/\/+$/, '');
  const doFetch = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  async function request<T>(
    method: string,
    path: string,
    body?: unknown,
    query?: Record<string, string>
  ): Promise<T> {
    const headers: Record<string, string> = { Accept: 'application/json' };
    const token = options.getToken?.();
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
    }
    const qs = query ? `?${new URLSearchParams(query).toString()}` : '';
    const response = await doFetch(`${baseUrl}${path}${qs}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      redirect: 'error',
    });
    const text = await response.text();
    if (!response.ok) {
      let parsed: ApiErrorBody;
      try {
        parsed = JSON.parse(text) as ApiErrorBody;
      } catch {
        parsed = {
          code: `HTTP_${response.status}`,
          message: text.slice(0, 200),
          requestId: response.headers.get('X-Request-Id') ?? '',
        };
      }
      const retry = Number.parseInt(response.headers.get('Retry-After') ?? '', 10);
      throw new ApiError(response.status, parsed, Number.isNaN(retry) ? null : retry);
    }
    return (text ? JSON.parse(text) : undefined) as T;
  }

  return {
    health: () =>
      request<{ status: string; service: string; version: string }>('GET', '/api/v1/health'),
    devToken: (subject: string) =>
      request<{ access_token: string; token_type: string; expires_in: number }>(
        'POST',
        '/api/v1/auth/dev-token',
        { subject }
      ),
    me: () => request<Me>('GET', '/api/v1/me'),
    skills: async () => (await request<{ skills: Skill[] }>('GET', '/api/v1/skills')).skills,
    searchApis: async (q: string, limit = 5) =>
      (
        await request<{ results: ApiSearchHit[] }>('GET', '/api/v1/apis/search', undefined, {
          q,
          limit: String(limit),
        })
      ).results,
    /**
     * With a conversation id, earlier turns give the agent context; if the conversation's
     * latest run is waiting for an answer, the server routes the message to it.
     */
    createRun: (query: string, environment = 'sandbox', conversationId?: string) => {
      if (conversationId !== undefined && !CONVERSATION_ID.test(conversationId)) {
        throw new Error(`invalid conversation id: ${conversationId}`);
      }
      return request<Run>('POST', '/api/v1/runs', {
        query,
        environment,
        ...(conversationId ? { conversation_id: conversationId } : {}),
      });
    },
    /** Starts the run in the background (202, status RUNNING); follow it with `streamRun`. */
    createRunAsync: (query: string, environment = 'sandbox', conversationId?: string) => {
      if (conversationId !== undefined && !CONVERSATION_ID.test(conversationId)) {
        throw new Error(`invalid conversation id: ${conversationId}`);
      }
      return request<Run>(
        'POST',
        '/api/v1/runs',
        {
          query,
          environment,
          ...(conversationId ? { conversation_id: conversationId } : {}),
        },
        { mode: 'async' }
      );
    },
    /** Resolves when the server closes the stream (the run finished or paused). */
    streamRun: (
      runId: string,
      onEvent: (event: RunProgressEvent) => void,
      streamOptions: { signal?: AbortSignal; lastEventId?: number } = {}
    ) => {
      assertRunId(runId);
      const token = options.getToken?.() ?? null;
      return readEventStream(
        `${baseUrl}/api/v1/runs/${runId}/events`,
        token ? { Authorization: `Bearer ${token}` } : {},
        onEvent,
        { fetchImpl: doFetch, ...streamOptions }
      );
    },
    createConversation: () => request<Conversation>('POST', '/api/v1/conversations'),
    getConversation: (conversationId: string) => {
      if (!CONVERSATION_ID.test(conversationId)) {
        throw new Error(`invalid conversation id: ${conversationId}`);
      }
      return request<Conversation>('GET', `/api/v1/conversations/${conversationId}`);
    },
    /** Answers a NEEDS_CLARIFICATION run; the blocked call is re-grounded, writes still need approval. */
    clarifyRun: (runId: string, message: string) => {
      assertRunId(runId);
      return request<Run>('POST', `/api/v1/runs/${runId}/clarify`, { message });
    },
    listRuns: async (status?: RunStatus, limit = 20) => {
      const query: Record<string, string> = { limit: String(limit) };
      if (status) {
        query.status = status;
      }
      return (await request<{ runs: Run[] }>('GET', '/api/v1/runs', undefined, query)).runs;
    },
    getRun: (runId: string) => {
      assertRunId(runId);
      return request<Run>('GET', `/api/v1/runs/${runId}`);
    },
    /** Approves exactly the action the user saw; the server rejects a stale hash. */
    approveRun: (runId: string, actionHash: string) => {
      assertRunId(runId);
      if (!ACTION_HASH.test(actionHash)) {
        throw new Error('invalid action hash');
      }
      return request<Run>('POST', `/api/v1/runs/${runId}/approve`, { action_hash: actionHash });
    },
    rejectRun: (runId: string, reason?: string) => {
      assertRunId(runId);
      return request<Run>('POST', `/api/v1/runs/${runId}/reject`, reason ? { reason } : {});
    },
  };
}

export type PlatformClient = ReturnType<typeof createClient>;

/** True when the run needs a human before it can continue. */
export function needsAction(run: Run): boolean {
  return run.status === 'AWAITING_APPROVAL' || run.status === 'NEEDS_CLARIFICATION';
}
