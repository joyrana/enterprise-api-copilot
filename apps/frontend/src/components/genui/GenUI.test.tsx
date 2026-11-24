import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Run } from '@/api/client';
import { GenUI } from './GenUI';

const baseRun: Run = {
  run_id: 'run_0123456789abcdef',
  status: 'COMPLETED',
  intent: 'api_discovery',
  query: 'which api refunds a payment?',
  environment: 'sandbox',
  message: 'Use `refundPayment`.',
  requested_by: 'alice',
  created_at: '2026-11-01T00:00:00Z',
  elapsed_s: 1,
  evidence: [],
  missing_fields: [],
  tool_calls: 1,
  pending_approval: null,
  timeline: [],
  mode: 'agentic',
};

describe('GenUI', () => {
  it('renders registered components and skips unknown ones', () => {
    render(
      <GenUI
        busy={false}
        decide={vi.fn()}
        run={{
          ...baseRun,
          ui: [
            {
              id: 'ui1',
              component: 'operation_list',
              source: 'search',
              props: {
                operations: [
                  {
                    operation_id: 'refundPayment',
                    api: 'Payments',
                    method: 'POST',
                    path: '/v1/payments/{payment_id}/refunds',
                    summary: 'Refund a payment',
                    scopes: ['refunds:write'],
                  },
                ],
              },
            },
            { id: 'ui2', component: 'hologram', source: null, props: {} },
          ],
        }}
      />
    );
    expect(screen.getByText('refundPayment')).toBeInTheDocument();
    expect(screen.getByText('Matching operations')).toBeInTheDocument();
  });

  it('always offers approval for a pending action, using the run hash', () => {
    const decide = vi.fn();
    const hash = 'a'.repeat(64);
    render(
      <GenUI
        busy={false}
        decide={decide}
        run={{
          ...baseRun,
          status: 'AWAITING_APPROVAL',
          ui: [],
          pending_approval: {
            step_id: 'call',
            skill_id: 'api.call.write',
            action_hash: hash,
            environment: 'sandbox',
            summary: 'POST /v1/payments',
          },
        }}
      />
    );
    expect(screen.getByText(`action hash ${hash}`)).toBeInTheDocument();
    screen.getByRole('button', { name: /approve exactly this/i }).click();
    expect(decide).toHaveBeenCalledWith(true);
  });

  it('lets the user answer a clarification when the page supports it', () => {
    const clarify = vi.fn();
    render(
      <GenUI
        busy={false}
        decide={vi.fn()}
        clarify={clarify}
        run={{
          ...baseRun,
          status: 'NEEDS_CLARIFICATION',
          missing_fields: ['body.amount'],
          ui: [
            {
              id: 'clarification',
              component: 'clarification',
              source: null,
              props: { missing_fields: ['body.amount'] },
            },
          ],
        }}
      />
    );
    fireEvent.change(screen.getByLabelText('Answer the question'), { target: { value: '₹500' } });
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect(clarify).toHaveBeenCalledWith('₹500');
  });

  it('shows no answer box where the page cannot clarify (e.g. history)', () => {
    render(
      <GenUI
        busy={false}
        decide={vi.fn()}
        run={{
          ...baseRun,
          status: 'NEEDS_CLARIFICATION',
          ui: [{ id: 'c', component: 'clarification', source: null, props: {} }],
        }}
      />
    );
    expect(screen.queryByLabelText('Answer the question')).toBeNull();
  });
});
