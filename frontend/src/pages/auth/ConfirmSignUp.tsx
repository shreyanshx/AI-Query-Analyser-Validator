import { useState, type FormEvent } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';

import { useAuth } from '../../auth/AuthContext';
import { authErrorMessage } from './authError';

interface LocationState {
  email?: string;
}

export function ConfirmSignUp(): JSX.Element {
  const { confirmSignUp, resendCode } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const initialEmail = (location.state as LocationState | null)?.email ?? '';

  const [email, setEmail] = useState(initialEmail);
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      await confirmSignUp(email, code);
      navigate('/login', { state: { email } });
    } catch (err) {
      setError(authErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function onResend() {
    setError(null);
    setNotice(null);
    try {
      await resendCode(email);
      setNotice('A new verification code has been sent to your email.');
    } catch (err) {
      setError(authErrorMessage(err));
    }
  }

  return (
    <div className="auth-card">
      <h1>Verify your email</h1>
      <p>Enter the verification code we emailed you.</p>
      <form onSubmit={onSubmit}>
        <label>
          Email
          <input
            type="email"
            value={email}
            autoComplete="username"
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
        <label>
          Verification code
          <input
            type="text"
            value={code}
            inputMode="numeric"
            onChange={(e) => setCode(e.target.value)}
            required
          />
        </label>
        {error && <p className="form-error">{error}</p>}
        {notice && <p className="form-notice">{notice}</p>}
        <button type="submit" disabled={busy}>
          {busy ? 'Verifying…' : 'Verify'}
        </button>
      </form>
      <div className="auth-links">
        <button type="button" className="link-button" onClick={onResend}>
          Resend code
        </button>
        <Link to="/login">Back to sign in</Link>
      </div>
    </div>
  );
}
