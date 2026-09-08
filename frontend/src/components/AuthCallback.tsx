// Completes the OAuth redirect: exchanges ?code= for tokens, then bounces to
// the panel. Its own tiny island so the exchange runs in the browser.
import { useEffect, useState } from 'preact/hooks';
import { handleCallback } from '../lib/auth';

export default function AuthCallback() {
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        await handleCallback();
        window.location.replace('/panel');
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, []);

  if (error) {
    return (
      <div class="gate">
        <h2>Logowanie nie powiodło się</h2>
        <p class="err">{error}</p>
        <a class="btn primary" href="/panel">
          Spróbuj ponownie
        </a>
      </div>
    );
  }
  return <p class="muted">Logowanie…</p>;
}
