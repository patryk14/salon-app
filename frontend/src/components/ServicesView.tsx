// Service catalog + rebooking (F8, admin). Sync services from visits, set a
// rebook interval + recommendation on the ones that matter, and see who's due
// to come back (for outreach — email reminders arrive with SES later).
import { useEffect, useState } from 'preact/hooks';
import { getUser, groupsOf, login } from '../lib/auth';
import { apiFetch } from '../lib/api';

interface Svc {
  id: number;
  name: string;
  visit_count: number;
  rebook_interval_days: number | null;
  recommendation: string | null;
  active: boolean;
}
interface Due {
  client_id: number;
  client_name: string;
  phone: string | null;
  service: string;
  last_visit: string;
  suggested_next: string;
}

export default function ServicesView() {
  const [ready, setReady] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [rows, setRows] = useState<Svc[]>([]);
  const [due, setDue] = useState<Due[]>([]);
  const [onlySet, setOnlySet] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      const user = await getUser();
      if (user && !user.expired) {
        if (!groupsOf(user).includes('admin')) {
          window.location.replace('/panel/pracownik');
          return;
        }
        setIsAdmin(true);
      }
      setReady(true);
    })();
  }, []);

  async function load() {
    setError(null);
    try {
      const [svc, d] = await Promise.all([
        apiFetch<Svc[]>('/catalog'),
        apiFetch<Due[]>('/catalog/due?within_days=14'),
      ]);
      setRows(svc);
      setDue(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (ready && isAdmin) load();
  }, [ready, isAdmin]);

  async function sync() {
    setBusy(true);
    setError(null);
    try {
      const s = await apiFetch<{ created: number; total: number }>('/catalog/sync', {
        method: 'POST',
      });
      setError(`Zsynchronizowano: ${s.total} usług (nowych ${s.created}).`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function patch(id: number, body: Record<string, unknown>) {
    try {
      await apiFetch(`/catalog/${id}`, { method: 'PATCH', body: JSON.stringify(body) });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  if (!ready) return <p class="muted">Ładowanie…</p>;
  if (!isAdmin) {
    return (
      <div class="gate">
        <h2>Usługi i przypomnienia</h2>
        <p class="muted">Zaloguj się, aby kontynuować.</p>
        <button class="btn primary" onClick={() => login()}>
          Zaloguj przez Cognito
        </button>
      </div>
    );
  }

  const shown = onlySet ? rows.filter((s) => s.rebook_interval_days != null) : rows;

  return (
    <div>
      {error && <div class="err">{error}</div>}

      <div class="bar">
        <button class="btn" disabled={busy} onClick={sync}>
          Synchronizuj z wizyt
        </button>
        <label class="chk">
          <input type="checkbox" checked={onlySet} onChange={(e) => setOnlySet((e.target as HTMLInputElement).checked)} />
          tylko z interwałem
        </label>
      </div>

      <div class="cat-head">
        <h2>Do przypomnienia ({due.length})</h2>
        <span class="muted small">klientki, którym zbliża się / minął termin kolejnej wizyty</span>
      </div>
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>Klientka</th>
              <th>Telefon</th>
              <th>Usługa</th>
              <th>Ostatnia</th>
              <th>Termin</th>
            </tr>
          </thead>
          <tbody>
            {due.map((d) => (
              <tr key={`${d.client_id}-${d.service}`}>
                <td>{d.client_name}</td>
                <td class="nowrap">{d.phone ?? '—'}</td>
                <td class="muted small">{d.service}</td>
                <td class="nowrap">{d.last_visit}</td>
                <td class="nowrap">
                  <b>{d.suggested_next}</b>
                </td>
              </tr>
            ))}
            {due.length === 0 && (
              <tr>
                <td colSpan={5} class="muted" style="text-align:center;padding:1.2rem">
                  Nikt nie czeka na przypomnienie.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <h2 class="section">Katalog usług ({rows.length})</h2>
      <p class="muted small">
        Ustaw interwał (co ile dni sugerować kolejną wizytę) i zalecenie dla najważniejszych usług —
        klientka zobaczy „sugerowany następny zabieg" w swoim profilu.
      </p>
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>Usługa</th>
              <th class="amt">Wizyt</th>
              <th>Interwał (dni)</th>
              <th>Zalecenie</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((s) => (
              <tr key={s.id}>
                <td>{s.name}</td>
                <td class="amt">{s.visit_count}</td>
                <td>
                  <input
                    class="cell num"
                    type="number"
                    min="1"
                    style="width:5rem"
                    placeholder="—"
                    value={s.rebook_interval_days ?? ''}
                    onBlur={(e) => {
                      const v = (e.target as HTMLInputElement).value;
                      if (v === (s.rebook_interval_days?.toString() ?? '')) return;
                      patch(s.id, v ? { rebook_interval_days: Number(v) } : { clear_interval: true });
                    }}
                  />
                </td>
                <td>
                  <input
                    class="cell"
                    style="width:100%"
                    placeholder="np. co 4 tygodnie"
                    defaultValue={s.recommendation ?? ''}
                    onBlur={(e) => {
                      const v = (e.target as HTMLInputElement).value;
                      if (v !== (s.recommendation ?? '')) patch(s.id, { recommendation: v });
                    }}
                  />
                </td>
              </tr>
            ))}
            {shown.length === 0 && (
              <tr>
                <td colSpan={4} class="muted" style="text-align:center;padding:1.2rem">
                  {rows.length === 0
                    ? 'Pusto — kliknij „Synchronizuj z wizyt".'
                    : 'Brak usług z ustawionym interwałem.'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
