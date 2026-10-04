import { useEffect, useState } from 'react';
import { Clock, RefreshCw } from 'lucide-react';
import { ApiError, type Run, type RunStatus } from '@/api/client';
import { platform, getToken } from '@/api/session';

const STATUSES: RunStatus[] = [
  'AWAITING_APPROVAL',
  'NEEDS_CLARIFICATION',
  'COMPLETED',
  'REJECTED',
  'FAILED',
];

const STATUS_COLOR: Record<RunStatus, string> = {
  RUNNING: 'text-blue-400',
  AWAITING_APPROVAL: 'text-amber-400',
  NEEDS_CLARIFICATION: 'text-amber-300',
  COMPLETED: 'text-green-400',
  REJECTED: 'text-red-400',
  FAILED: 'text-red-400',
};

type Load =
  | { state: 'idle' | 'loading' }
  | { state: 'error'; message: string }
  | { state: 'ready'; runs: Run[] };

/**
 * Run history from GET /api/v1/runs (tenant-scoped, newest first). Filtering by
 * "Awaiting approval" gives the approval queue; approvals happen on the Chat page or
 * with `copilot runs approve`. Errors are shown as errors — never as an empty list.
 */
export function HistoryPage() {
  const [status, setStatus] = useState<RunStatus | ''>('');
  const [load, setLoad] = useState<Load>({ state: 'idle' });
  const [selected, setSelected] = useState<Run | null>(null);

  const refresh = async () => {
    if (!getToken()) {
      setLoad({ state: 'error', message: 'Sign in on the Chat page to see your runs.' });
      return;
    }
    setLoad({ state: 'loading' });
    try {
      setLoad({ state: 'ready', runs: await platform.listRuns(status || undefined, 50) });
    } catch (err) {
      const message =
        err instanceof ApiError
          ? `${err.code} (HTTP ${err.status}): ${err.message}`
          : 'Could not load runs';
      setLoad({ state: 'error', message });
    }
  };

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Run History</h1>
          <p className="text-gray-400 text-sm mt-1">
            Every request, its outcome and its execution timeline.
          </p>
        </div>
        <button
          onClick={() => void refresh()}
          className="px-3 py-1.5 rounded-lg border border-gray-700 flex items-center gap-1 text-sm"
        >
          <RefreshCw className="w-4 h-4" /> Refresh
        </button>
      </div>

      <label className="flex items-center gap-3 text-sm text-gray-300">
        Status
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value as RunStatus | '')}
          className="bg-gray-800 border border-gray-700 text-gray-300 text-sm rounded-lg px-3 py-2 outline-none"
        >
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s === 'AWAITING_APPROVAL'
                ? 'Awaiting approval (queue)'
                : s.toLowerCase().replace('_', ' ')}
            </option>
          ))}
        </select>
      </label>

      {load.state === 'loading' && <p className="text-sm text-gray-400">Loading…</p>}
      {load.state === 'error' && (
        <p role="alert" className="card text-sm text-red-300">
          {load.message}
        </p>
      )}
      {load.state === 'ready' && load.runs.length === 0 && (
        <div className="card text-center py-16">
          <Clock className="w-10 h-10 text-gray-600 mx-auto mb-4" />
          <p className="text-gray-400 font-medium">No runs match this filter</p>
        </div>
      )}
      {load.state === 'ready' && load.runs.length > 0 && (
        <div className="card p-0 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800">
                <th className="text-left px-6 py-3 text-gray-400 font-medium">Request</th>
                <th className="text-left px-6 py-3 text-gray-400 font-medium">Status</th>
                <th className="text-left px-6 py-3 text-gray-400 font-medium">By</th>
                <th className="text-left px-6 py-3 text-gray-400 font-medium">Created</th>
              </tr>
            </thead>
            <tbody>
              {load.runs.map((run) => (
                <tr
                  key={run.run_id}
                  onClick={() => setSelected(run)}
                  className="border-b border-gray-800 hover:bg-gray-800/50 cursor-pointer"
                >
                  <td className="px-6 py-4 text-gray-200 max-w-xs truncate">{run.query}</td>
                  <td className={`px-6 py-4 ${STATUS_COLOR[run.status]}`}>{run.status}</td>
                  <td className="px-6 py-4 text-gray-400">{run.requested_by}</td>
                  <td className="px-6 py-4 text-gray-500">
                    {new Date(run.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <section className="card space-y-2" aria-label="Run details">
          <h2 className="text-lg font-semibold text-white">
            {selected.run_id} · {selected.status}
          </h2>
          <p className="whitespace-pre-wrap text-sm text-gray-200">{selected.message}</p>
          {selected.pending_approval && (
            <p className="text-sm text-amber-300">
              Pending: {selected.pending_approval.summary} (hash{' '}
              {selected.pending_approval.action_hash.slice(0, 12)}…)
            </p>
          )}
          <h3 className="text-sm font-medium text-gray-300 pt-2">Timeline</h3>
          <ol className="text-sm text-gray-400 list-decimal pl-5">
            {selected.timeline.map((event, i) => (
              <li key={i}>
                {event.kind}
                {event.detail && 'skill_id' in event.detail
                  ? ` — ${String(event.detail.skill_id)}`
                  : ''}
                {event.detail && 'error' in event.detail && event.detail.error
                  ? ` (${String(event.detail.error)})`
                  : ''}
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}
