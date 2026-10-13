/**
 * Authenticated axios client.
 *
 * - Request interceptor attaches the current Cognito ACCESS token, refreshing
 *   via `getSession()` when the cached token is near expiry.
 * - Response interceptor redirects to /login on 401.
 */

import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios';

import { getSession, type SessionTokens } from '../auth/cognito';
import { isTokenNearExpiry } from '../auth/tokenUtils';
import { config } from '../config';
import type {
  ConnectionConfig,
  ConnectionInfo,
  OptimizeRequest,
  OptimizeResponse,
  TestConnectionResponse,
  ValidateRequest,
  ValidationResult,
} from './types';

export const api = axios.create({
  baseURL: config.apiBaseUrl || '',
  headers: { 'Content-Type': 'application/json' },
});

// Cached tokens so we only refresh when near expiry.
let cachedTokens: SessionTokens | null = null;

async function currentAccessToken(): Promise<string | null> {
  if (cachedTokens && !isTokenNearExpiry(cachedTokens.accessTokenExpiry)) {
    return cachedTokens.accessToken;
  }
  try {
    cachedTokens = await getSession();
    return cachedTokens.accessToken;
  } catch {
    cachedTokens = null;
    return null;
  }
}

/** Clear the in-memory token cache (used on logout). */
export function clearTokenCache(): void {
  cachedTokens = null;
}

api.interceptors.request.use(async (request: InternalAxiosRequestConfig) => {
  const token = await currentAccessToken();
  if (token) {
    request.headers.set('Authorization', `Bearer ${token}`);
  }
  return request;
});

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      cachedTokens = null;
      if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
        window.location.assign('/login');
      }
    }
    return Promise.reject(error);
  },
);

// --- Typed API functions matching the backend contract ---------------------

export async function testConnection(cfg: ConnectionConfig): Promise<TestConnectionResponse> {
  const { data } = await api.post<TestConnectionResponse>('/api/connections/test', cfg);
  return data;
}

export async function listConnections(): Promise<ConnectionInfo[]> {
  const { data } = await api.get<ConnectionInfo[]>('/api/connections');
  return data;
}

export async function validateSql(req: ValidateRequest): Promise<ValidationResult> {
  const { data } = await api.post<ValidationResult>('/api/validate', req);
  return data;
}

export async function optimizeSql(req: OptimizeRequest): Promise<OptimizeResponse> {
  const { data } = await api.post<OptimizeResponse>('/api/optimize', req);
  return data;
}
