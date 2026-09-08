// @ts-check
import { defineConfig, envField } from 'astro/config';
import preact from '@astrojs/preact';

// The frontend is fully static: `npm run build` → dist/ → S3 + CloudFront.
// No SSR and no adapter — on purpose (cheap, zero servers to maintain). The
// admin panel runs entirely in the browser: Cognito Hosted UI + PKCE for login,
// then fetch() to the API with the bearer token. Authorization is enforced in
// the API; the panel only hides what a role can't use.
// https://astro.build/config
export default defineConfig({
  output: 'static',
  integrations: [preact()],
  env: {
    // Single source of default + type. All PUBLIC (context: client) — compiled
    // into the bundle at build time. NONE are secrets: the API URL and the
    // Cognito identifiers (pool, client id, hosted-UI domain) are public by
    // design (a browser SPA cannot hold a secret; PKCE is the protection).
    schema: {
      PUBLIC_API_URL: envField.string({
        context: 'client',
        access: 'public',
        default: 'http://localhost:8000',
      }),
      PUBLIC_COGNITO_AUTHORITY: envField.string({
        context: 'client',
        access: 'public',
        default: 'https://cognito-idp.eu-central-1.amazonaws.com/eu-central-1_uWBM7LTRv',
      }),
      PUBLIC_COGNITO_CLIENT_ID: envField.string({
        context: 'client',
        access: 'public',
        default: '7rl6qhkurb1bn598rvjvu7k4pg',
      }),
      PUBLIC_COGNITO_DOMAIN: envField.string({
        context: 'client',
        access: 'public',
        default: 'https://charmskin-381492053759.auth.eu-central-1.amazoncognito.com',
      }),
    },
  },
});
