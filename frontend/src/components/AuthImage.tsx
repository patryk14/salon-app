// An <img> whose bytes are fetched WITH the bearer token and shown from an
// in-memory blob. There is no URL that opens a client's photo on its own: the
// blob: address works only inside this tab and dies with it, so nothing useful
// can leak through history, copy-paste or logs.
import { useEffect, useState } from 'preact/hooks';
import { apiFetchBlob } from '../lib/api';

// The API gateway throttles at 10 req/s — load a gallery a few photos at a time.
const MAX_PARALLEL = 4;
let active = 0;
const waiting: (() => void)[] = [];
async function withSlot<T>(job: () => Promise<T>): Promise<T> {
  if (active >= MAX_PARALLEL) await new Promise<void>((go) => waiting.push(go));
  active++;
  try {
    return await job();
  } finally {
    active--;
    waiting.shift()?.();
  }
}

export default function AuthImage({ path, alt }: { path: string; alt: string }) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;
    setSrc(null);
    setFailed(false);
    withSlot(() => apiFetchBlob(path))
      .then((blob) => {
        if (cancelled) return;
        url = URL.createObjectURL(blob);
        setSrc(url);
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [path]);

  if (failed) return <div class="ph ph-err">nie udało się wczytać</div>;
  if (!src) return <div class="ph">wczytywanie…</div>;
  return (
    <a href={src} target="_blank" rel="noopener">
      <img src={src} alt={alt} />
    </a>
  );
}
