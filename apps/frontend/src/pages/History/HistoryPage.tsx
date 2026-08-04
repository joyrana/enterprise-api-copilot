import { Clock, CheckCircle, XCircle, Loader2 } from 'lucide-react';

type ExecutionStatus = 'COMPLETED' | 'FAILED' | 'RUNNING' | 'PENDING';

interface ExecutionRecord {
  id: string;
  naturalQuery: string;
  apiMethod: string;
  apiUrl: string;
  status: ExecutionStatus;
  responseStatus: number | null;
  createdAt: string;
}

const STATUS_CONFIG: Record<ExecutionStatus, { icon: React.ComponentType<{ className?: string }>; color: string; label: string }> = {
  COMPLETED: { icon: CheckCircle, color: 'text-green-400', label: 'Completed' },
  FAILED: { icon: XCircle, color: 'text-red-400', label: 'Failed' },
  RUNNING: { icon: Loader2, color: 'text-brand-400', label: 'Running' },
  PENDING: { icon: Clock, color: 'text-yellow-400', label: 'Pending' },
};

/**
 * History page — displays past API executions with replay capability.
 *
 * TODO(#40): Connect to GET /api/v1/executions with pagination.
 * TODO(#41): Implement replay functionality.
 * TODO(#42): Add filter by status, date range, API path.
 */
export function HistoryPage() {
  // TODO(#40): Replace with real data from useExecutionHistory hook
  const executions: ExecutionRecord[] = [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Execution History</h1>
        <p className="text-gray-400 text-sm mt-1">
          Browse and replay past API executions.
        </p>
      </div>

      {/* Filters placeholder */}
      <div className="flex gap-3">
        <select className="bg-gray-800 border border-gray-700 text-gray-300 text-sm rounded-lg px-3 py-2 outline-none">
          <option>All statuses</option>
          <option>Completed</option>
          <option>Failed</option>
        </select>
      </div>

      {/* Table */}
      {executions.length === 0 ? (
        <div className="card text-center py-16">
          <Clock className="w-10 h-10 text-gray-600 mx-auto mb-4" />
          <p className="text-gray-400 font-medium">No executions yet</p>
          <p className="text-gray-500 text-sm mt-1">
            Start a conversation and run an API to see it here.
          </p>
        </div>
      ) : (
        <div className="card p-0 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800">
                <th className="text-left px-6 py-3 text-gray-400 font-medium">Query</th>
                <th className="text-left px-6 py-3 text-gray-400 font-medium">API</th>
                <th className="text-left px-6 py-3 text-gray-400 font-medium">Status</th>
                <th className="text-left px-6 py-3 text-gray-400 font-medium">Time</th>
              </tr>
            </thead>
            <tbody>
              {executions.map((exec) => {
                const config = STATUS_CONFIG[exec.status];
                const Icon = config.icon;
                return (
                  <tr key={exec.id} className="border-b border-gray-800 hover:bg-gray-800/50">
                    <td className="px-6 py-4 text-gray-200 max-w-xs truncate">{exec.naturalQuery}</td>
                    <td className="px-6 py-4 font-mono text-gray-400">
                      <span className="text-brand-400 mr-2">{exec.apiMethod}</span>
                      {exec.apiUrl}
                    </td>
                    <td className="px-6 py-4">
                      <span className={`flex items-center gap-1.5 ${config.color}`}>
                        <Icon className="w-3.5 h-3.5" />
                        {config.label}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-gray-500">{exec.createdAt}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
