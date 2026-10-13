/** Normalize unknown thrown values (Cognito errors, Error, strings) to text. */
export function authErrorMessage(err: unknown): string {
  if (err && typeof err === 'object' && 'message' in err) {
    const message = (err as { message?: unknown }).message;
    if (typeof message === 'string' && message.length > 0) {
      return message;
    }
  }
  if (typeof err === 'string') {
    return err;
  }
  return 'Something went wrong. Please try again.';
}
