/**
 * Runtime configuration sourced from Vite environment variables.
 *
 * The frontend never handles AWS credentials or any provider API key. Only the
 * public Cognito User Pool identifiers (pool id + public app client id with NO
 * client secret) and the API base URL are read here.
 */

export interface AppConfig {
  cognitoUserPoolId: string;
  cognitoAppClientId: string;
  awsRegion: string;
  /** Base URL for the backend API. Empty string means use the dev proxy. */
  apiBaseUrl: string;
}

function readEnv(key: string): string {
  const value = import.meta.env[key as keyof ImportMetaEnv];
  return typeof value === 'string' ? value : '';
}

export const config: AppConfig = {
  cognitoUserPoolId: readEnv('VITE_COGNITO_USER_POOL_ID'),
  cognitoAppClientId: readEnv('VITE_COGNITO_APP_CLIENT_ID'),
  awsRegion: readEnv('VITE_AWS_REGION'),
  apiBaseUrl: readEnv('VITE_API_BASE_URL'),
};
