import type { Run } from '@/api/client';
import { GenUIContext } from './context';
import { COMPONENT_REGISTRY, componentsFor } from './registry';

/** Renders the components the agent chose for a run, in order. */
export function GenUI({
  run,
  decide,
  busy,
  clarify,
  canDecide,
}: {
  run: Run;
  decide: (approve: boolean) => void;
  busy: boolean;
  clarify?: (message: string) => void;
  canDecide?: boolean;
}) {
  return (
    <GenUIContext.Provider value={{ run, decide, busy, clarify, canDecide }}>
      {componentsFor(run).map((c) => {
        const Component = COMPONENT_REGISTRY[c.component];
        return Component ? <Component key={c.id} data={c.props} /> : null;
      })}
    </GenUIContext.Provider>
  );
}
