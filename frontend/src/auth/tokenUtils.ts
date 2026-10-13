/**
 * Pure helpers for reasoning about token expiry. Kept dependency-free so they
 * are trivially unit-testable.
 */

/** Default skew window (seconds) treated as "near expiry". */
export const DEFAULT_EXPIRY_SKEW_SECONDS = 60;

/**
 * Return true when an access token with the given expiry (seconds since epoch)
 * is expired or within `skewSeconds` of expiring.
 */
export function isTokenNearExpiry(
  expiryEpochSeconds: number,
  nowEpochSeconds: number = Math.floor(Date.now() / 1000),
  skewSeconds: number = DEFAULT_EXPIRY_SKEW_SECONDS,
): boolean {
  return expiryEpochSeconds - skewSeconds <= nowEpochSeconds;
}
