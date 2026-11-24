import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Run } from '@/api/client';

const run: Run = {
  run_id: 'run_0123456789abcdef',
  status: 'AWAITING_APPROVAL',
  intent: 'api_execution',
  query: 'create a payment',
  environment: 'sandbox',
  message: 'Approval required',
  requested_by: 'alice',
  created_at: '2026-11-01T00:00:00Z',
  elapsed_s: 1,
  evidence: [],
  missing_fields: [],
  tool_calls: 2,
  pending_approval: {
    step_id: 'call',
    skill_id: 'api.call.write',
    action_hash: 'b'.repeat(64),
    environment: 'sandbox',
    summary: 'POST /v1/payments',
  },
  timeline: [],
  ui: [{ id: 'approval', component: 'approval_request', source: 'call', props: {} }],
};

const platform = vi.hoisted(() => ({
  me: vi.fn(),
  listRuns: vi.fn(),
  approveRun: vi.fn(),
  rejectRun: vi.fn(),
  clarifyRun: vi.fn(),
}));
vi.mock('@/api/session', () => ({ platform, getToken: () => 'tok' }));

import { HistoryPage } from './HistoryPage';

describe('HistoryPage renders past runs with the same components as chat', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    platform.listRuns.mockResolvedValue([run]);
  });

  it('hides the approve button from non-approvers', async () => {
    platform.me.mockResolvedValue({ subject: 'alice', tenant_id: 'acme', roles: ['developer'] });
    render(<HistoryPage />);
    fireEvent.click(await screen.findByText('create a payment'));
    expect(await screen.findByText(/You do not have the approver role/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Approve exactly this/ })).toBeNull();
  });

  it('lets an approver approve exactly the pending hash', async () => {
    platform.me.mockResolvedValue({ subject: 'priya', tenant_id: 'acme', roles: ['approver'] });
    platform.approveRun.mockResolvedValue({ ...run, status: 'COMPLETED', pending_approval: null });
    render(<HistoryPage />);
    fireEvent.click(await screen.findByText('create a payment'));
    fireEvent.click(await screen.findByRole('button', { name: /Approve exactly this/ }));
    await waitFor(() =>
      expect(platform.approveRun).toHaveBeenCalledWith('run_0123456789abcdef', 'b'.repeat(64))
    );
    expect(await screen.findByText(/No longer pending/)).toBeInTheDocument();
  });

  it('shows no approval buttons for runs that are not pending', async () => {
    platform.me.mockResolvedValue({ subject: 'priya', tenant_id: 'acme', roles: ['approver'] });
    platform.listRuns.mockResolvedValue([{ ...run, status: 'COMPLETED', pending_approval: null }]);
    render(<HistoryPage />);
    fireEvent.click(await screen.findByText('create a payment'));
    expect(screen.queryByRole('button', { name: /Approve exactly this/ })).toBeNull();
  });
});
