// Cognito login for the static SPA: Hosted UI + OAuth code flow with PKCE.
// The client is public (no secret) — PKCE binds the code exchange to this
// browser. Tokens live in sessionStorage (per-tab, cleared on close; NOT
// localStorage): the redirect flow needs them to survive the callback
// navigation, and the CSP (no third-party JS) is the real XSS mitigation.
//
// The panel only DECIDES what to show; every request is re-authorized by the
// API. A stolen/expired token gets 401 there, not a false sense of safety here.
import {
  UserManager,
  WebStorageStateStore,
  type User,
} from 'oidc-client-ts';
import {
  PUBLIC_COGNITO_AUTHORITY,
  PUBLIC_COGNITO_CLIENT_ID,
  PUBLIC_COGNITO_DOMAIN,
} from 'astro:env/client';

// Built once, in the browser (origin differs local vs prod → redirect_uri too).
function buildManager(): UserManager {
  const origin = window.location.origin;
  return new UserManager({
    authority: PUBLIC_COGNITO_AUTHORITY,
    client_id: PUBLIC_COGNITO_CLIENT_ID,
    redirect_uri: `${origin}/panel/callback`,
    post_logout_redirect_uri: `${origin}/`,
    response_type: 'code',
    scope: 'openid email profile',
    // Explicit endpoints (Hosted UI domain) rather than discovery — Cognito's
    // authorize/token/logout live on the auth domain, jwks on the issuer.
    metadata: {
      issuer: PUBLIC_COGNITO_AUTHORITY,
      authorization_endpoint: `${PUBLIC_COGNITO_DOMAIN}/oauth2/authorize`,
      token_endpoint: `${PUBLIC_COGNITO_DOMAIN}/oauth2/token`,
      userinfo_endpoint: `${PUBLIC_COGNITO_DOMAIN}/oauth2/userInfo`,
      end_session_endpoint: `${PUBLIC_COGNITO_DOMAIN}/logout`,
      jwks_uri: `${PUBLIC_COGNITO_AUTHORITY}/.well-known/jwks.json`,
    },
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
    stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
    automaticSilentRenew: true,
  });
}

let manager: UserManager | null = null;
function mgr(): UserManager {
  if (manager === null) manager = buildManager();
  return manager;
}

export async function login(): Promise<void> {
  await mgr().signinRedirect();
}

export async function logout(): Promise<void> {
  // Cognito's /logout needs the client_id + logout_uri; oidc-client-ts appends
  // them from post_logout_redirect_uri. Also clears the local user.
  await mgr().signoutRedirect({
    extraQueryParams: {
      client_id: PUBLIC_COGNITO_CLIENT_ID,
      logout_uri: `${window.location.origin}/`,
    },
  });
}

// Complete the redirect: exchange ?code= for tokens. Called on /panel/callback.
export async function handleCallback(): Promise<User> {
  return mgr().signinRedirectCallback();
}

export async function getUser(): Promise<User | null> {
  return mgr().getUser();
}

// The access token to send to the API, or null if not signed in / expired.
export async function getAccessToken(): Promise<string | null> {
  const user = await mgr().getUser();
  if (!user || user.expired) return null;
  return user.access_token;
}

// Cognito puts group membership in the access token's `cognito:groups`.
export function groupsOf(user: User): string[] {
  const profile = user.profile as Record<string, unknown>;
  const groups = profile['cognito:groups'];
  return Array.isArray(groups) ? (groups as string[]) : [];
}
