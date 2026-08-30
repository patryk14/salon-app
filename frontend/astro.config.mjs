// @ts-check
import { defineConfig, envField } from 'astro/config';

// The frontend is fully static: `npm run build` → dist/ → S3 + CloudFront.
// No SSR and no adapter — on purpose (cheap, zero servers to maintain).
// https://astro.build/config
export default defineConfig({
  output: 'static',
  env: {
    // The single place holding the default value and type (`astro:env/client`) — instead
    // of a hand-written env.d.ts and `?? 'http://localhost:8000'` in every file. The value
    // is compiled into the bundle at build time (context: client, access: public) — never secrets.
    schema: {
      PUBLIC_API_URL: envField.string({
        context: 'client',
        access: 'public',
        default: 'http://localhost:8000',
      }),
    },
  },
});
