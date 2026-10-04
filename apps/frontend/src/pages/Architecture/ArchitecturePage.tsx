/**
 * Architecture page — visual overview of the platform architecture.
 */
export function ArchitecturePage() {
  return (
    <div className="space-y-8 max-w-5xl">
      <div>
        <h1 className="text-2xl font-bold text-white">Architecture</h1>
        <p className="text-gray-400 text-sm mt-1">
          System design, component boundaries, and data flows.
        </p>
      </div>

      {/* Mermaid Architecture Diagram Source */}
      <div className="card">
        <h2 className="text-sm font-semibold text-gray-300 mb-4 uppercase tracking-wider">
          System Overview
        </h2>
        <pre className="text-xs text-gray-400 font-mono leading-relaxed overflow-x-auto">
{`graph TD
  Developer --> CLI
  Developer --> Frontend
  CLI --> Backend
  Frontend --> Backend
  Backend --> Supervisor
  Supervisor --> Planner
  Planner --> SkillRouter
  SkillRouter --> APIDiscovery[api.discovery]
  SkillRouter --> APIExecutor[api.executor]
  SkillRouter --> SDKGenerator[api.sdk_generator]
  SkillRouter --> JWT[jwt]
  SkillRouter --> Docs[docs]
  SkillRouter --> GitHub[github]
  APIExecutor --> Apigee
  Apigee --> EnterpriseAPIs[Enterprise APIs]`}
        </pre>
      </div>

      {/* Component Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {[
          {
            title: 'Backend',
            tech: 'Spring Boot 3 · Java 21 · Maven',
            description: 'Central control plane. Exposes REST APIs. Orchestrates agents. Enforces auth.',
            status: '🚧 Skeleton',
          },
          {
            title: 'Frontend',
            tech: 'React 18 · TypeScript · Vite · TailwindCSS',
            description: 'Developer dashboard with chat, execution history, and architecture views.',
            status: '🚧 Skeleton',
          },
          {
            title: 'CLI',
            tech: 'Go 1.22 · Cobra · BubbleTea',
            description: 'Single-binary developer CLI. login, ask, api, doctor commands.',
            status: '🚧 Skeleton',
          },
          {
            title: 'AI Agents',
            tech: 'Python 3.12 · LangGraph · OpenAI',
            description: 'Supervisor, Planner, Reflection, Memory agents in a stateful graph.',
            status: '📋 Planned',
          },
          {
            title: 'MCP Skills',
            tech: 'Python · MCP Protocol',
            description: 'Stateless tools grouped as api/, docs/, jwt/, github/.',
            status: '📋 Planned',
          },
          {
            title: 'Apigee',
            tech: 'Apigee X · OAuth 2.0 · JWT',
            description: 'Enterprise API gateway for auth, quota, analytics, and proxying.',
            status: '📋 Planned',
          },
        ].map((item) => (
          <div key={item.title} className="card">
            <div className="flex items-start justify-between mb-2">
              <h3 className="text-sm font-semibold text-white">{item.title}</h3>
              <span className="text-xs text-gray-500">{item.status}</span>
            </div>
            <p className="text-xs font-mono text-brand-400 mb-2">{item.tech}</p>
            <p className="text-sm text-gray-400">{item.description}</p>
          </div>
        ))}
      </div>

      <div className="card border-gray-700">
        <p className="text-sm text-gray-400">
          For detailed architecture documentation, see{' '}
          <a
            href="https://github.com/joyrana/enterprise-api-copilot/blob/main/docs/architecture.md"
            target="_blank"
            rel="noopener noreferrer"
            className="text-brand-400 hover:underline"
          >
            docs/architecture.md
          </a>{' '}
          and the{' '}
          <a
            href="https://github.com/joyrana/enterprise-api-copilot/blob/main/docs/adr/ADR-0001.md"
            target="_blank"
            rel="noopener noreferrer"
            className="text-brand-400 hover:underline"
          >
            Architecture Decision Records
          </a>.
        </p>
      </div>
    </div>
  );
}
