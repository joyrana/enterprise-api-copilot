import { afterEach, describe, expect, it, vi } from 'vitest';

import { getToken, setToken } from './session.ts';

describe('session token storage', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    sessionStorage.clear();
  });

  it('returns null when no token is stored', () => {
    expect(getToken()).toBeNull();
  });

  it('stores the token in sessionStorage, not localStorage', () => {
    setToken('tok_123');

    expect(getToken()).toBe('tok_123');
    expect(sessionStorage.getItem('copilot.token')).toBe('tok_123');
    expect(localStorage.getItem('copilot.token')).toBeNull();
  });

  it('clears the token when given null', () => {
    setToken('tok_123');
    setToken(null);

    expect(getToken()).toBeNull();
  });

  it('treats unavailable storage as signed out instead of throwing', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });

    expect(() => setToken('tok_123')).not.toThrow();
    expect(getToken()).toBeNull();
  });
});
