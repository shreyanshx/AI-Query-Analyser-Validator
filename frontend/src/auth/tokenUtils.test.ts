import { describe, expect, it } from 'vitest';

import { isTokenNearExpiry } from './tokenUtils';

describe('isTokenNearExpiry', () => {
  const now = 1_000_000;

  it('is false for a token well in the future', () => {
    expect(isTokenNearExpiry(now + 3600, now)).toBe(false);
  });

  it('is true for an already expired token', () => {
    expect(isTokenNearExpiry(now - 10, now)).toBe(true);
  });

  it('is true within the default skew window', () => {
    expect(isTokenNearExpiry(now + 30, now)).toBe(true);
  });

  it('respects a custom skew', () => {
    expect(isTokenNearExpiry(now + 120, now, 60)).toBe(false);
    expect(isTokenNearExpiry(now + 120, now, 180)).toBe(true);
  });
});
