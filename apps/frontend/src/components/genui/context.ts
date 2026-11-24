import { createContext, useContext } from 'react';
import type { Run } from '@/api/client';

/** Actions a generative-UI component may trigger on the run it belongs to. */
export interface GenUIActions {
  run: Run | null;
  decide: (approve: boolean) => void;
  busy: boolean;
  /** Answers a NEEDS_CLARIFICATION run; absent where the page cannot (e.g. history). */
  clarify?: (message: string) => void;
}

export const GenUIContext = createContext<GenUIActions>({
  run: null,
  decide: () => undefined,
  busy: false,
});

export const useGenUIActions = () => useContext(GenUIContext);
