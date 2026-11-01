import { useState, type ReactNode } from 'react';
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  Code2,
  KeyRound,
  ListTree,
  Server,
  ShieldCheck,
  ShieldX,
  Workflow,
  XCircle,
} from 'lucide-react';
import { useGenUIActions } from './context';

/**
 * Presentational components for the generative-UI registry. Each one renders props the
 * server built from real step output (ai/agent/ui.py), so nothing here fabricates data.
 */

type Props = Record<string, unknown>;

const asArray = <T,>(value: unknown): T[] => (Array.isArray(value) ? (value as T[]) : []);
const asString = (value: unknown): string => (typeof value === 'string' ? value : '');

const METHOD_COLORS: Record<string, string> = {
  GET: 'bg-emerald-900 text-emerald-300',
  POST: 'bg-sky-900 text-sky-300',
  PUT: 'bg-amber-900 text-amber-300',
  PATCH: 'bg-amber-900 text-amber-300',
  DELETE: 'bg-red-900 text-red-300',
};

function Method({ method }: { method: string }) {
  return (
    <span className={`badge font-mono ${METHOD_COLORS[method] ?? 'bg-gray-800 text-gray-300'}`}>
      {method}
    </span>
  );
}

function Panel({
  icon,
  title,
  children,
  tone = 'default',
}: {
  icon: ReactNode;
  title: ReactNode;
  children: ReactNode;
  tone?: 'default' | 'warning';
}) {
  return (
    <section
      className={`mt-3 rounded-lg border ${
        tone === 'warning' ? 'border-amber-700 bg-amber-950/30' : 'border-gray-700 bg-gray-900/60'
      } p-3 space-y-2`}
    >
      <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-gray-400">
        {icon}
        {title}
      </h3>
      {children}
    </section>
  );
}

function Pre({ children }: { children: string }) {
  return (
    <pre className="overflow-x-auto rounded-md bg-gray-950 p-3 text-xs text-gray-200 whitespace-pre">
      {children}
    </pre>
  );
}

interface Operation {
  operation_id: string;
  api: string;
  method: string;
  path: string;
  summary: string;
  scopes: string[];
}

export function OperationList({ data }: { data: Props }) {
  const operations = asArray<Operation>(data.operations);
  return (
    <Panel icon={<ListTree className="w-4 h-4" />} title="Matching operations">
      {operations.length === 0 ? (
        <p className="text-gray-400">No operations found.</p>
      ) : (
        <ul className="divide-y divide-gray-800">
          {operations.map((op) => (
            <li key={op.operation_id} className="py-2 flex flex-col gap-1">
              <div className="flex items-center gap-2 flex-wrap">
                <Method method={op.method} />
                <code className="text-gray-100">{op.path}</code>
                <span className="text-brand-500 font-mono text-xs">{op.operation_id}</span>
              </div>
              <p className="text-gray-400 text-xs">
                {op.summary} · {op.api}
                {op.scopes?.length ? ` · scopes: ${op.scopes.join(', ')}` : ''}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

interface Param {
  name: string;
  location: string;
  required: boolean;
  description: string;
}
interface BodyField {
  name: string;
  type: string | null;
  required: boolean;
  description: string;
  enum: unknown[] | null;
}

export function OperationDetail({ data }: { data: Props }) {
  const params = asArray<Param>(data.parameters);
  const fields = asArray<BodyField>(data.body_fields);
  const responses = (data.responses ?? {}) as Record<string, string>;
  return (
    <Panel
      icon={<Server className="w-4 h-4" />}
      title={
        <span className="normal-case tracking-normal flex items-center gap-2">
          <Method method={asString(data.method)} />
          <code className="text-gray-100">{asString(data.path)}</code>
          <span className="text-brand-500 font-mono">{asString(data.operation_id)}</span>
        </span>
      }
    >
      <p className="text-gray-300">{asString(data.description) || asString(data.summary)}</p>
      <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-gray-500">API</dt>
        <dd>
          {asString(data.api_title)} {asString(data.api_version)}
        </dd>
        <dt className="text-gray-500">Auth</dt>
        <dd>{asString(data.authentication)}</dd>
        <dt className="text-gray-500">Scopes</dt>
        <dd className="font-mono">{asArray<string>(data.scopes).join(', ') || 'none'}</dd>
        {data.side_effect ? (
          <>
            <dt className="text-gray-500">Side effect</dt>
            <dd>{asString(data.side_effect)}</dd>
          </>
        ) : null}
      </dl>
      {params.length > 0 && (
        <table className="w-full text-xs">
          <thead className="text-gray-500 text-left">
            <tr>
              <th className="py-1">Parameter</th>
              <th>In</th>
              <th>Description</th>
            </tr>
          </thead>
          <tbody>
            {params.map((p) => (
              <tr key={`${p.location}.${p.name}`} className="border-t border-gray-800">
                <td className="py-1 font-mono">
                  {p.name}
                  {p.required && <span className="text-red-400">*</span>}
                </td>
                <td>{p.location}</td>
                <td className="text-gray-400">{p.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {fields.length > 0 && (
        <table className="w-full text-xs">
          <thead className="text-gray-500 text-left">
            <tr>
              <th className="py-1">Body field</th>
              <th>Type</th>
              <th>Description</th>
            </tr>
          </thead>
          <tbody>
            {fields.map((f) => (
              <tr key={f.name} className="border-t border-gray-800">
                <td className="py-1 font-mono">
                  {f.name}
                  {f.required && <span className="text-red-400">*</span>}
                </td>
                <td className="font-mono">{f.enum ? f.enum.join(' | ') : f.type}</td>
                <td className="text-gray-400">{f.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {Object.keys(responses).length > 0 && (
        <ul className="text-xs flex flex-wrap gap-2">
          {Object.entries(responses).map(([code, text]) => (
            <li key={code} className="badge bg-gray-800 text-gray-300" title={text}>
              {code} {text}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export function CodeSnippets({ data }: { data: Props }) {
  const snippets = (data.snippets ?? {}) as Record<string, string>;
  const languages = Object.keys(snippets);
  const [active, setActive] = useState(languages[0] ?? '');
  return (
    <Panel
      icon={<Code2 className="w-4 h-4" />}
      title={`Code samples · ${asString(data.operation_id)}`}
    >
      <div role="tablist" className="flex gap-1">
        {languages.map((lang) => (
          <button
            key={lang}
            role="tab"
            aria-selected={lang === active}
            onClick={() => setActive(lang)}
            className={`px-2 py-0.5 rounded text-xs ${
              lang === active ? 'bg-brand-600 text-white' : 'bg-gray-800 text-gray-300'
            }`}
          >
            {lang}
          </button>
        ))}
      </div>
      {active && <Pre>{snippets[active] ?? ''}</Pre>}
      {asArray<string>(data.notes).map((note) => (
        <p key={note} className="text-xs text-gray-400">
          {note}
        </p>
      ))}
    </Panel>
  );
}

export function ApiResponse({ data }: { data: Props }) {
  const ok = data.ok === true;
  const body =
    data.response_body !== null && data.response_body !== undefined
      ? JSON.stringify(data.response_body, null, 2)
      : asString(data.response_preview);
  return (
    <Panel
      icon={
        ok ? (
          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
        ) : (
          <XCircle className="w-4 h-4 text-red-400" />
        )
      }
      title={
        <span className="normal-case tracking-normal flex items-center gap-2">
          <Method method={asString(data.method)} />
          <code className="text-gray-100">{asString(data.path)}</code>
          <span className={ok ? 'text-emerald-400' : 'text-red-400'}>
            HTTP {String(data.status_code ?? '')}
          </span>
        </span>
      }
    >
      {data.correlation_id ? (
        <p className="text-xs text-gray-500 font-mono">
          correlation {asString(data.correlation_id)}
        </p>
      ) : null}
      {data.retry_after_s ? (
        <p className="text-xs text-amber-300">Retry after {String(data.retry_after_s)} s</p>
      ) : null}
      {body && <Pre>{body}</Pre>}
      {data.curl ? (
        <details>
          <summary className="cursor-pointer text-xs text-gray-400">Equivalent cURL</summary>
          <Pre>{asString(data.curl)}</Pre>
        </details>
      ) : null}
    </Panel>
  );
}

interface Source {
  source_id: string;
  title: string;
  section: string;
  uri: string;
  flagged: boolean;
}

export function DocSources({ data }: { data: Props }) {
  const sources = asArray<Source>(data.sources).filter((s) => !s.flagged);
  const flagged = asArray<Source>(data.sources).length - sources.length;
  return (
    <Panel icon={<BookOpen className="w-4 h-4" />} title="Documentation sources">
      <ol className="list-decimal list-inside text-xs space-y-1">
        {sources.map((s) => (
          <li key={s.source_id}>
            <span className="text-gray-200">{s.title}</span>
            {s.section && <span className="text-gray-500"> · {s.section}</span>}
            {s.uri && <span className="text-gray-600 font-mono"> · {s.uri}</span>}
          </li>
        ))}
      </ol>
      {flagged > 0 && (
        <p className="text-xs text-amber-300">
          {flagged} source(s) were excluded because they looked like prompt injection.
        </p>
      )}
    </Panel>
  );
}

export function JwtReport({ data }: { data: Props }) {
  const issues = asArray<string>(data.issues);
  const claims = (data.claims ?? {}) as Record<string, string>;
  return (
    <Panel
      icon={<KeyRound className="w-4 h-4" />}
      title="Token inspection"
      tone={issues.length ? 'warning' : 'default'}
    >
      <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-gray-500">Algorithm</dt>
        <dd className="font-mono">{asString(data.algorithm) || 'unknown'}</dd>
        <dt className="text-gray-500">Expires</dt>
        <dd>
          {asString(data.expires_at) || 'never'}
          {data.expired === true && <span className="text-red-400"> (expired)</span>}
        </dd>
        <dt className="text-gray-500">Scopes</dt>
        <dd className="font-mono">{asArray<string>(data.scopes).join(' ') || 'none'}</dd>
        {asArray<string>(data.missing_scopes).length > 0 && (
          <>
            <dt className="text-gray-500">Missing</dt>
            <dd className="font-mono text-red-300">
              {asArray<string>(data.missing_scopes).join(' ')}
            </dd>
          </>
        )}
        {Object.entries(claims).map(([k, v]) => (
          <span key={k} className="contents">
            <dt className="text-gray-500 font-mono">{k}</dt>
            <dd className="font-mono">{v}</dd>
          </span>
        ))}
      </dl>
      <ul className="text-xs space-y-1">
        {issues.length === 0 ? (
          <li className="text-emerald-300">No problems detected.</li>
        ) : (
          issues.map((issue) => (
            <li key={issue} className="flex gap-1 text-amber-200">
              <AlertTriangle className="w-3 h-3 mt-0.5 flex-shrink-0" /> {issue}
            </li>
          ))
        )}
      </ul>
      <p className="text-xs text-gray-500">{asString(data.note)}</p>
    </Panel>
  );
}

interface TraceStep {
  step_id: string;
  skill_id: string;
  purpose: string;
  ok: boolean | null;
  duration_ms: number | null;
}

export function RunTrace({ data }: { data: Props }) {
  const steps = asArray<TraceStep>(data.steps);
  return (
    <Panel icon={<Workflow className="w-4 h-4" />} title={`Agent steps · ${asString(data.mode)}`}>
      <ol className="text-xs space-y-1">
        {steps.map((s, i) => (
          <li key={s.step_id} className="flex gap-2">
            <span className="text-gray-500 w-4">{i + 1}.</span>
            <span className="font-mono text-brand-500">{s.skill_id}</span>
            <span className="text-gray-400 flex-1">{s.purpose}</span>
            <span className={s.ok ? 'text-emerald-400' : s.ok === false ? 'text-red-400' : ''}>
              {s.ok === null ? 'pending' : s.ok ? 'ok' : 'failed'}
            </span>
          </li>
        ))}
      </ol>
    </Panel>
  );
}

export function ApprovalRequest({ data }: { data: Props }) {
  const { run, decide, busy } = useGenUIActions();
  // The hash sent back always comes from the run's authoritative pending approval.
  const pending = run?.pending_approval;
  const actionable = run?.status === 'AWAITING_APPROVAL' && pending;
  return (
    <Panel icon={<ShieldCheck className="w-4 h-4" />} title="Approval required" tone="warning">
      <p>{pending?.summary ?? asString(data.summary)}</p>
      <p className="font-mono text-xs break-all text-gray-400">
        action hash {pending?.action_hash ?? asString(data.action_hash)}
      </p>
      {actionable ? (
        <div className="flex gap-2">
          <button
            onClick={() => decide(true)}
            disabled={busy}
            className="btn-primary px-3 py-1 flex items-center gap-1"
          >
            <ShieldCheck className="w-4 h-4" /> Approve exactly this
          </button>
          <button
            onClick={() => decide(false)}
            disabled={busy}
            className="px-3 py-1 rounded-lg border border-gray-700 flex items-center gap-1"
          >
            <ShieldX className="w-4 h-4" /> Reject
          </button>
        </div>
      ) : (
        <p className="text-xs text-gray-500">No longer pending.</p>
      )}
    </Panel>
  );
}

export function Clarification({ data }: { data: Props }) {
  const fields = asArray<string>(data.missing_fields);
  return (
    <Panel
      icon={<AlertTriangle className="w-4 h-4" />}
      title="More information needed"
      tone="warning"
    >
      {fields.length > 0 ? (
        <ul className="flex flex-wrap gap-2">
          {fields.map((f) => (
            <li key={f} className="badge bg-amber-900 text-amber-200 font-mono">
              {f.includes('.') ? f.split('.').slice(1).join('.') : f}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="text-xs text-gray-400">Reply with the missing values to continue.</p>
    </Panel>
  );
}
