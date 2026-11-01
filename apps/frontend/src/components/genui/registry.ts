import type { ComponentType } from 'react';
import type { Run, UIComponent } from '@/api/client';
import {
  ApiResponse,
  ApprovalRequest,
  Clarification,
  CodeSnippets,
  DocSources,
  JwtReport,
  OperationDetail,
  OperationList,
  RunTrace,
} from './components';

/**
 * Component registry: the client half of ai/agent/ui.py. The agent chooses components
 * by name; unknown names are skipped, so a newer server never breaks an older client.
 */
export const COMPONENT_REGISTRY: Record<
  string,
  ComponentType<{ data: Record<string, unknown> }>
> = {
  operation_list: OperationList,
  operation_detail: OperationDetail,
  code_snippets: CodeSnippets,
  api_response: ApiResponse,
  doc_sources: DocSources,
  jwt_report: JwtReport,
  run_trace: RunTrace,
  approval_request: ApprovalRequest,
  clarification: Clarification,
};

/** Components to render for a run; adds the approval panel if an older server omitted it. */
export function componentsFor(run: Run): UIComponent[] {
  const ui = run.ui ?? [];
  if (run.pending_approval && !ui.some((c) => c.component === 'approval_request')) {
    return [...ui, { id: 'approval', component: 'approval_request', source: null, props: {} }];
  }
  return ui;
}
