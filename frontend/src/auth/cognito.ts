/**
 * Thin wrapper around amazon-cognito-identity-js.
 *
 * Uses a PUBLIC Cognito app client with NO client secret. The browser only
 * ever handles the user's own tokens; it never touches AWS credentials or any
 * provider API key.
 */

import {
  AuthenticationDetails,
  CognitoUser,
  CognitoUserAttribute,
  CognitoUserPool,
  CognitoUserSession,
  type ISignUpResult,
} from 'amazon-cognito-identity-js';

import { config } from '../config';

const userPool = new CognitoUserPool({
  UserPoolId: config.cognitoUserPoolId,
  ClientId: config.cognitoAppClientId,
});

export interface SessionTokens {
  accessToken: string;
  idToken: string;
  refreshToken: string;
  /** Access-token expiry, seconds since epoch. */
  accessTokenExpiry: number;
}

function cognitoUser(email: string): CognitoUser {
  return new CognitoUser({ Username: email, Pool: userPool });
}

function toSessionTokens(session: CognitoUserSession): SessionTokens {
  const accessToken = session.getAccessToken();
  return {
    accessToken: accessToken.getJwtToken(),
    idToken: session.getIdToken().getJwtToken(),
    refreshToken: session.getRefreshToken().getToken(),
    accessTokenExpiry: accessToken.getExpiration(),
  };
}

/** Register a new user. Cognito emails a confirmation code. */
export function signUp(email: string, password: string): Promise<ISignUpResult> {
  const attributes = [new CognitoUserAttribute({ Name: 'email', Value: email })];
  return new Promise((resolve, reject) => {
    userPool.signUp(email, password, attributes, [], (err, result) => {
      if (err || !result) {
        reject(err ?? new Error('Sign-up failed'));
        return;
      }
      resolve(result);
    });
  });
}

/** Confirm a sign-up with the emailed verification code. */
export function confirmSignUp(email: string, code: string): Promise<void> {
  return new Promise((resolve, reject) => {
    cognitoUser(email).confirmRegistration(code, true, (err) => {
      if (err) {
        reject(err);
        return;
      }
      resolve();
    });
  });
}

/** Resend the email verification code. */
export function resendCode(email: string): Promise<void> {
  return new Promise((resolve, reject) => {
    cognitoUser(email).resendConfirmationCode((err) => {
      if (err) {
        reject(err);
        return;
      }
      resolve();
    });
  });
}

/** Authenticate and return the resulting session tokens. */
export function signIn(email: string, password: string): Promise<SessionTokens> {
  const user = cognitoUser(email);
  const details = new AuthenticationDetails({ Username: email, Password: password });
  return new Promise((resolve, reject) => {
    user.authenticateUser(details, {
      onSuccess: (session) => resolve(toSessionTokens(session)),
      onFailure: (err) => reject(err),
    });
  });
}

/** Sign the current user out locally (clears cached tokens). */
export function signOut(): void {
  const user = userPool.getCurrentUser();
  if (user) {
    user.signOut();
  }
}

/** Return the currently signed-in user's email, if any. */
export function getCurrentUsername(): string | null {
  return userPool.getCurrentUser()?.getUsername() ?? null;
}

/**
 * Return a valid session, refreshing the access token automatically when it is
 * expired. Rejects when there is no current user or the refresh token is no
 * longer valid.
 */
export function getSession(): Promise<SessionTokens> {
  const user = userPool.getCurrentUser();
  if (!user) {
    return Promise.reject(new Error('No authenticated user'));
  }
  return new Promise((resolve, reject) => {
    user.getSession((err: Error | null, session: CognitoUserSession | null) => {
      if (err || !session) {
        reject(err ?? new Error('No session'));
        return;
      }
      if (session.isValid()) {
        resolve(toSessionTokens(session));
        return;
      }
      const refreshToken = session.getRefreshToken();
      user.refreshSession(refreshToken, (refreshErr, refreshed) => {
        if (refreshErr || !refreshed) {
          reject(refreshErr ?? new Error('Session refresh failed'));
          return;
        }
        resolve(toSessionTokens(refreshed));
      });
    });
  });
}

/** Start a forgot-password flow; Cognito emails a reset code. */
export function forgotPassword(email: string): Promise<void> {
  const user = cognitoUser(email);
  return new Promise((resolve, reject) => {
    user.forgotPassword({
      onSuccess: () => resolve(),
      onFailure: (err) => reject(err),
    });
  });
}

/** Complete a forgot-password flow with the emailed code and a new password. */
export function confirmForgotPassword(
  email: string,
  code: string,
  newPassword: string,
): Promise<void> {
  const user = cognitoUser(email);
  return new Promise((resolve, reject) => {
    user.confirmPassword(code, newPassword, {
      onSuccess: () => resolve(),
      onFailure: (err) => reject(err),
    });
  });
}
