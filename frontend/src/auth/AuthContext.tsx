/**
 * Authentication context + provider.
 *
 * Exposes the current user, session tokens, and the Cognito auth methods to the
 * app. Tokens live in memory (plus the SDK's own storage); the DB password is
 * never stored here or in localStorage.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import { clearTokenCache } from '../api/client';
import * as cognito from './cognito';
import type { SessionTokens } from './cognito';

interface AuthContextValue {
  username: string | null;
  tokens: SessionTokens | null;
  isAuthenticated: boolean;
  loading: boolean;
  signUp: typeof cognito.signUp;
  confirmSignUp: typeof cognito.confirmSignUp;
  resendCode: typeof cognito.resendCode;
  forgotPassword: typeof cognito.forgotPassword;
  confirmForgotPassword: typeof cognito.confirmForgotPassword;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }): JSX.Element {
  const [tokens, setTokens] = useState<SessionTokens | null>(null);
  const [username, setUsername] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const session = await cognito.getSession();
      setTokens(session);
      setUsername(cognito.getCurrentUsername());
    } catch {
      setTokens(null);
      setUsername(null);
    }
  }, []);

  useEffect(() => {
    void refresh().finally(() => setLoading(false));
  }, [refresh]);

  const login = useCallback(async (email: string, password: string) => {
    const session = await cognito.signIn(email, password);
    setTokens(session);
    setUsername(cognito.getCurrentUsername());
  }, []);

  const logout = useCallback(() => {
    cognito.signOut();
    clearTokenCache();
    setTokens(null);
    setUsername(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      username,
      tokens,
      isAuthenticated: Boolean(tokens),
      loading,
      signUp: cognito.signUp,
      confirmSignUp: cognito.confirmSignUp,
      resendCode: cognito.resendCode,
      forgotPassword: cognito.forgotPassword,
      confirmForgotPassword: cognito.confirmForgotPassword,
      login,
      logout,
      refresh,
    }),
    [username, tokens, loading, login, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
}
