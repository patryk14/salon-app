// Clients + progress photos (F9, staff & admin). Find a client, record her photo
// consent, upload before/after photos and browse her gallery. Photo bytes never
// pass through the API: the browser PUTs straight to the private bucket with a
// short-lived presigned URL, then registers the object. RODO erasure is admin-only.
import { useEffect, useRef, useState } from 'preact/hooks';
import { getUser, groupsOf, login } from '../lib/auth';
import { apiFetch } from '../lib/api';
import AuthImage from './AuthImage';
import BeautyPlanEditor from './BeautyPlanEditor';
import TreatmentCards from './TreatmentCards';

interface Client {
  id: number;
  first_name: string;
  last_name: string;
  phone: string | null;
  email: string | null;
  photo_consent: boolean;
  photo_consent_at: string | null;
}
interface Page<T> {
  items: T[];
  total: number;
}
interface Visit {
  id: number;
  starts_at: string;
  service_name: string;
}
interface Photo {
  id: number;
  visit_id: number | null;
  kind: 'before' | 'after' | null;
  note: string | null;
  taken_on: string | null;
  created_at: string;
}

const KIND_LABEL: Record<string, string> = { before: 'Przed', after: 'Po' };
const MAX_EDGE = 2000; // px — plenty for progress photos, ~10× smaller than a phone original

// Re-encode through a canvas before upload: caps the size (galleries stay fast,
// storage stays cheap) and — importantly for RODO — drops EXIF, so a client's
// photo never carries GPS coordinates or device data into the bucket.
async function prepareImage(file: File): Promise<Blob> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext('2d')!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('Nie udało się przetworzyć zdjęcia'))), 'image/jpeg', 0.85),
  );
}

export default function ClientsView() {
  const [ready, setReady] = useState(false);
  const [isStaff, setIsStaff] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [q, setQ] = useState('');
  const [results, setResults] = useState<Client[]>([]);
  const [total, setTotal] = useState(0);
  const [client, setClient] = useState<Client | null>(null);
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [visits, setVisits] = useState<Visit[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<'photos' | 'cards' | 'plan'>('photos');
  const [mySub, setMySub] = useState<string | null>(null);
  const [services, setServices] = useState<string[]>([]);
  // upload form
  const fileRef = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState('');
  const [visitId, setVisitId] = useState('');
  const [takenOn, setTakenOn] = useState('');
  const [note, setNote] = useState('');
  // inline edit of the profile's basic data
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ first_name: '', last_name: '', phone: '', email: '' });
  // merge (admin): fold this duplicate into the real profile
  const [mergeQ, setMergeQ] = useState('');
  const [mergeHits, setMergeHits] = useState<Client[]>([]);

  useEffect(() => {
    (async () => {
      const user = await getUser();
      if (user && !user.expired) {
        const g = groupsOf(user);
        setIsStaff(g.includes('staff') || g.includes('admin'));
        setIsAdmin(g.includes('admin'));
        setMySub(user.profile.sub);
        // treatment-name suggestions for the beauty plan (best effort)
        if (g.includes('staff') || g.includes('admin'))
          apiFetch<string[]>('/services').then(setServices).catch(() => {});
      }
      setReady(true);
    })();
  }, []);

  // debounced search
  useEffect(() => {
    if (!ready || !isStaff) return;
    const t = setTimeout(async () => {
      try {
        const page = await apiFetch<Page<Client>>(
          `/clients?limit=30${q.trim() ? `&q=${encodeURIComponent(q.trim())}` : ''}`,
        );
        setResults(page.items);
        setTotal(page.total);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    }, 250);
    return () => clearTimeout(t);
  }, [q, ready, isStaff]);

  // debounced target search for the merge box
  useEffect(() => {
    if (!client || mergeQ.trim().length < 2) {
      setMergeHits([]);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const page = await apiFetch<Page<Client>>(
          `/clients?limit=8&q=${encodeURIComponent(mergeQ.trim())}`,
        );
        setMergeHits(page.items.filter((c) => c.id !== client.id));
      } catch {
        setMergeHits([]);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [mergeQ, client?.id]);

  async function mergeInto(target: Client) {
    if (!client) return;
    const from = `${client.first_name} ${client.last_name}`;
    const to = `${target.first_name} ${target.last_name}`;
    if (
      !confirm(
        `Scalić profil „${from}" (#${client.id}) z „${to}" (#${target.id})?\n\n` +
          `Wizyty, zdjęcia, pakiety i konto w portalu przejdą na „${to}", a profil „${from}" zniknie. ` +
          `Tej operacji nie da się cofnąć.`,
      )
    )
      return;
    try {
      const merged = await apiFetch<Client>(`/clients/${client.id}/merge-into/${target.id}`, {
        method: 'POST',
      });
      setResults((rs) => rs.filter((r) => r.id !== client.id).map((r) => (r.id === merged.id ? merged : r)));
      await open(merged);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function startEdit() {
    if (!client) return;
    setForm({
      first_name: client.first_name,
      // "?" is the import placeholder for a missing surname — don't make her retype over it
      last_name: client.last_name === '?' ? '' : client.last_name,
      phone: client.phone ?? '',
      email: client.email ?? '',
    });
    setEditing(true);
  }

  async function saveEdit() {
    if (!client) return;
    if (!form.first_name.trim() || !form.last_name.trim()) {
      setError('Imię i nazwisko są wymagane.');
      return;
    }
    try {
      const updated = await apiFetch<Client>(`/clients/${client.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          first_name: form.first_name.trim(),
          last_name: form.last_name.trim(),
          phone: form.phone.trim() || null,
          email: form.email.trim() || null,
        }),
      });
      setClient(updated);
      setResults((rs) => rs.map((r) => (r.id === updated.id ? updated : r)));
      setEditing(false);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function open(c: Client) {
    setError(null);
    setMergeQ('');
    setEditing(false);
    setClient(c);
    setPhotos([]);
    setVisits([]);
    try {
      const [ph, vs] = await Promise.all([
        apiFetch<Photo[]>(`/clients/${c.id}/photos`),
        apiFetch<Page<Visit>>(`/clients/${c.id}/visits?limit=50`),
      ]);
      setPhotos(ph);
      setVisits(vs.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function setConsent(value: boolean) {
    if (!client) return;
    if (!value && !confirm('Cofnąć zgodę? Nowe zdjęcia nie będą mogły być dodawane (istniejące zostają).')) return;
    try {
      const updated = await apiFetch<Client>(`/clients/${client.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ photo_consent: value }),
      });
      setClient(updated);
      setResults((rs) => rs.map((r) => (r.id === updated.id ? updated : r)));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function upload() {
    const file = fileRef.current?.files?.[0];
    if (!client) return;
    if (!file) {
      setError('Najpierw wybierz plik ze zdjęciem.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const blob = await prepareImage(file);
      const slot = await apiFetch<{ s3_key: string; upload_url: string; content_type: string }>(
        `/clients/${client.id}/photos/upload-url`,
        { method: 'POST', body: JSON.stringify({ content_type: 'image/jpeg' }) },
      );
      // Straight to the bucket — no API, no bearer token; the URL itself is the grant.
      const put = await fetch(slot.upload_url, {
        method: 'PUT',
        headers: { 'Content-Type': slot.content_type },
        body: blob,
      });
      if (!put.ok) throw new Error(`Upload do magazynu nie powiódł się (${put.status})`);
      await apiFetch(`/clients/${client.id}/photos`, {
        method: 'POST',
        body: JSON.stringify({
          s3_key: slot.s3_key,
          content_type: slot.content_type,
          kind: kind || null,
          visit_id: visitId ? Number(visitId) : null,
          taken_on: takenOn || null,
          note: note.trim() || null,
        }),
      });
      if (fileRef.current) fileRef.current.value = '';
      setNote('');
      setPhotos(await apiFetch<Photo[]>(`/clients/${client.id}/photos`));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function removePhoto(p: Photo) {
    if (!client || !confirm('Usunąć to zdjęcie? Operacja jest nieodwracalna.')) return;
    try {
      await apiFetch(`/photos/${p.id}`, { method: 'DELETE' });
      setPhotos((ps) => ps.filter((x) => x.id !== p.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function erase() {
    if (!client) return;
    const name = `${client.first_name} ${client.last_name}`;
    const typed = prompt(
      `RODO — trwałe usunięcie WSZYSTKICH danych klientki (profil, wizyty, zdjęcia).\n` +
        `Nie zostanie też ponownie zaimportowana z Booksy. Otwarte zamówienia ze sklepu zostaną anulowane.\n` +
        `WAŻNE: usuń ją także w Booksy — to osobny system i stamtąd jej dane nie znikną same.\n\nAby potwierdzić, wpisz: ${name}`,
    );
    if (typed?.trim() !== name) return;
    try {
      await apiFetch(`/clients/${client.id}/erase`, { method: 'POST' });
      setResults((rs) => rs.filter((r) => r.id !== client.id));
      setClient(null);
      setError(`Dane klientki „${name}" zostały trwale usunięte.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  if (!ready) return <p class="muted">Ładowanie…</p>;
  if (!isStaff) {
    return (
      <div class="gate">
        <h2>Klientki i zdjęcia</h2>
        <p class="muted">Zaloguj się, aby kontynuować.</p>
        <button class="btn primary" onClick={() => login()}>
          Zaloguj przez Cognito
        </button>
      </div>
    );
  }

  const visitLabel = (id: number | null) => {
    const v = visits.find((x) => x.id === id);
    return v ? `${v.starts_at.slice(0, 10)} · ${v.service_name}` : null;
  };

  return (
    <div class="split">
      <aside class="list">
        <input
          class="search"
          type="search"
          placeholder="Szukaj: imię, nazwisko, telefon…"
          value={q}
          onInput={(e) => setQ((e.target as HTMLInputElement).value)}
        />
        <p class="muted small">
          {total} {q.trim() ? 'pasujących' : 'klientek'}
          {total > results.length ? ` (pokazano ${results.length})` : ''}
        </p>
        <ul>
          {results.map((c) => (
            <li key={c.id}>
              <button class={`row${client?.id === c.id ? ' active' : ''}`} onClick={() => open(c)}>
                <span>
                  {c.last_name} {c.first_name}
                </span>
                <span class="muted small">{c.phone ?? ''}</span>
                {c.photo_consent && <span class="badge ok">foto</span>}
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <section class="detail">
        {error && <div class="err">{error}</div>}
        {!client && <p class="muted">Wybierz klientkę z listy.</p>}
        {client && (
          <div>
            {!editing ? (
              <div class="cat-head">
                <h2>
                  {client.first_name} {client.last_name}
                </h2>
                <span class="muted small">
                  {[client.phone, client.email].filter(Boolean).join(' · ') || 'brak kontaktu'}{' '}
                  <button class="link" onClick={startEdit}>
                    Edytuj dane
                  </button>
                </span>
              </div>
            ) : (
              <div class="card edit">
                {(
                  [
                    ['first_name', 'Imię'],
                    ['last_name', 'Nazwisko'],
                    ['phone', 'Telefon'],
                    ['email', 'E-mail'],
                  ] as const
                ).map(([key, label]) => (
                  <label class="fld" key={key}>
                    <span class="lbl">{label}</span>
                    <input
                      type={key === 'email' ? 'email' : 'text'}
                      value={form[key]}
                      onInput={(e) => setForm({ ...form, [key]: (e.target as HTMLInputElement).value })}
                    />
                  </label>
                ))}
                <div class="edit-actions">
                  <button class="btn primary sm" onClick={saveEdit}>
                    Zapisz
                  </button>
                  <button class="btn sm" onClick={() => setEditing(false)}>
                    Anuluj
                  </button>
                </div>
              </div>
            )}

            <div class="tabs">
              {(
                [
                  ['photos', `Zdjęcia (${photos.length})`],
                  ['cards', 'Karty zabiegowe'],
                  ['plan', 'Beauty plan'],
                ] as const
              ).map(([key, label]) => (
                <button key={key} class={`tab${tab === key ? ' active' : ''}`} onClick={() => setTab(key)}>
                  {label}
                </button>
              ))}
            </div>

            {tab === 'cards' && (
              <TreatmentCards clientId={client.id} visits={visits} isAdmin={isAdmin} mySub={mySub} />
            )}
            {tab === 'plan' && <BeautyPlanEditor clientId={client.id} services={services} />}

            {tab === 'photos' && (
              <div>
              <div class="card">
                <label class="chk strong">
                  <input
                    type="checkbox"
                    checked={client.photo_consent}
                    onChange={(e) => setConsent((e.target as HTMLInputElement).checked)}
                  />
                  Zgoda na zdjęcia postępów
                </label>
                <p class="muted small">
                  {client.photo_consent
                    ? `Udzielona ${client.photo_consent_at?.slice(0, 10) ?? ''}. Zdjęcia są prywatne — widzi je tylko salon i sama klientka.`
                    : 'Bez zgody klientki nie można dodawać zdjęć. Zaznacz po jej uzyskaniu (najlepiej pisemnie).'}
                </p>
              </div>

              {client.photo_consent && (
                <div class="card upload">
                  <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" />
                  <select value={kind} onChange={(e) => setKind((e.target as HTMLSelectElement).value)}>
                    <option value="">bez oznaczenia</option>
                    <option value="before">Przed</option>
                    <option value="after">Po</option>
                  </select>
                  <select value={visitId} onChange={(e) => setVisitId((e.target as HTMLSelectElement).value)}>
                    <option value="">bez wizyty</option>
                    {visits.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.starts_at.slice(0, 10)} · {v.service_name}
                      </option>
                    ))}
                  </select>
                  <input
                    type="date"
                    title="Data wykonania (domyślnie dziś)"
                    value={takenOn}
                    onInput={(e) => setTakenOn((e.target as HTMLInputElement).value)}
                  />
                  <input
                    class="grow"
                    placeholder="notatka (opcjonalnie)"
                    value={note}
                    onInput={(e) => setNote((e.target as HTMLInputElement).value)}
                  />
                  <button class="btn primary" disabled={busy} onClick={upload}>
                    {busy ? 'Wysyłanie…' : 'Dodaj zdjęcie'}
                  </button>
                </div>
              )}

              <h2 class="section">Galeria ({photos.length})</h2>
              {photos.length === 0 && <p class="muted">Brak zdjęć.</p>}
              <div class="grid">
                {photos.map((p) => (
                  <figure key={p.id}>
                    <AuthImage path={`/photos/${p.id}/content`} alt={p.note ?? 'zdjęcie postępów'} />
                    <figcaption>
                      <span>
                        {p.kind && <span class={`badge ${p.kind}`}>{KIND_LABEL[p.kind]}</span>}{' '}
                        {p.taken_on}
                      </span>
                      {visitLabel(p.visit_id) && <span class="muted small">{visitLabel(p.visit_id)}</span>}
                      {p.note && <span class="small">{p.note}</span>}
                      <button class="link danger" onClick={() => removePhoto(p)}>
                        usuń
                      </button>
                    </figcaption>
                  </figure>
                ))}
              </div>
              </div>
            )}

            {isAdmin && (
              <div class="card merge">
                <b>Duplikat? Scal z właściwym profilem</b>
                <p class="muted small">
                  Ten profil (#{client.id}) zostanie wchłonięty: jego wizyty, zdjęcia, pakiety i konto
                  w portalu przejdą na wybrany profil.
                </p>
                <input
                  type="search"
                  placeholder="Szukaj właściwego profilu…"
                  value={mergeQ}
                  onInput={(e) => setMergeQ((e.target as HTMLInputElement).value)}
                />
                {mergeHits.length > 0 && (
                  <ul class="hits">
                    {mergeHits.map((h) => (
                      <li key={h.id}>
                        <span>
                          {h.first_name} {h.last_name}{' '}
                          <span class="muted small">
                            #{h.id} {[h.phone, h.email].filter(Boolean).join(' · ')}
                          </span>
                        </span>
                        <button class="btn sm" onClick={() => mergeInto(h)}>
                          Scal z tym
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {isAdmin && (
              <div class="card rodo">
                <div>
                  <b>RODO — prawo do bycia zapomnianą</b>
                  <p class="muted small">
                    Trwale usuwa profil, wizyty i wszystkie zdjęcia (także z magazynu) oraz blokuje
                    ponowny import tej osoby z Booksy.
                  </p>
                </div>
                <button class="btn danger" onClick={erase}>
                  Usuń wszystkie dane
                </button>
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
