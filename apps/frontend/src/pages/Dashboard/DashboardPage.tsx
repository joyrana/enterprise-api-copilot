import { Link } from 'react-router-dom';
import { MessageSquare, History, Zap, ArrowRight } from 'lucide-react';

const STATS = [
  { label: 'API Calls Today', value: '—', trend: null },
  { label: 'Conversations', value: '—', trend: null },
  { label: 'APIs Discovered', value: '—', trend: null },
  { label: 'Avg Response Time', value: '—', trend: null },
];

const QUICK_ACTIONS = [
  {
    title: 'Start a conversation',
    description: 'Ask in natural language — "List all payment APIs"',
    icon: MessageSquare,
    to: '/chat',
    color: 'text-brand-400',
  },
  {
    title: 'View execution history',
    description: 'Browse past API executions and replay them',
    icon: History,
    to: '/history',
    color: 'text-purple-400',
  },
];

/**
 * Dashboard page — overview of platform activity and quick actions.
 *
 * TODO(#20): Connect stats cards to real backend metrics API.
 * TODO(#21): Add recent executions table.
 * TODO(#22): Add API catalog health summary.
 */
export function DashboardPage() {
  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Dashboard</h1>
        <p className="text-gray-400 mt-1">
          Your enterprise API activity at a glance.
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {STATS.map((stat) => (
          <div key={stat.label} className="card">
            <p className="text-xs text-gray-400 uppercase tracking-wider">{stat.label}</p>
            <p className="text-3xl font-bold text-white mt-2">{stat.value}</p>
          </div>
        ))}
      </div>

      {/* Quick Actions */}
      <div>
        <h2 className="text-lg font-semibold text-white mb-4">Quick Actions</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {QUICK_ACTIONS.map(({ title, description, icon: Icon, to, color }) => (
            <Link
              key={to}
              to={to}
              className="card hover:border-gray-600 transition-colors group cursor-pointer"
            >
              <div className="flex items-start gap-4">
                <div className={`mt-0.5 ${color}`}>
                  <Icon className="w-6 h-6" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-white">{title}</p>
                  <p className="text-sm text-gray-400 mt-1">{description}</p>
                </div>
                <ArrowRight className="w-4 h-4 text-gray-600 group-hover:text-gray-400 transition-colors mt-0.5" />
              </div>
            </Link>
          ))}
        </div>
      </div>

      {/* Getting Started */}
      <div className="card border-brand-600/30 bg-brand-600/5">
        <div className="flex items-center gap-3 mb-3">
          <Zap className="w-5 h-5 text-brand-400" />
          <h3 className="text-sm font-semibold text-brand-300">Getting Started</h3>
        </div>
        <p className="text-sm text-gray-400 mb-4">
          Enterprise API Copilot is in early development. The platform is being initialized.
          Check back soon for working features.
        </p>
        <div className="flex gap-3">
          <a
            href="https://github.com/your-org/enterprise-api-copilot"
            target="_blank"
            rel="noopener noreferrer"
            className="btn-primary text-sm"
          >
            View on GitHub
          </a>
          <Link to="/architecture" className="btn-secondary text-sm">
            Architecture
          </Link>
        </div>
      </div>
    </div>
  );
}
