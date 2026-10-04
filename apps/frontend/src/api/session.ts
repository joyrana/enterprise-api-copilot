/**
 * Browser session for the platform token. sessionStorage (not localStorage) so the token
 * does not outlive the tab; all access is guarded because storage can be unavailable.
 */
import { createClient } from './client.ts';

const KEY = 'copilot.token';

export function getToken(): string | null {
  try {
    return globalThis.sessionStorage?.getItem(KEY) ?? null;
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) {
      globalThis.sessionStorage?.setItem(KEY, token);
    } else {
      globalThis.sessionStorage?.removeItem(KEY);
    }
  } catch {
    // storage unavailable: the user signs in again next time
  }
}

/** Same-origin client; the Vite dev server proxies /api to the platform. */
export const platform = createClient({ getToken });
