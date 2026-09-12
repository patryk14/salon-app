// Visits browser — see the visits pulled from Booksy. Also surfaces the DISTINCT
// staff names Booksy uses, so mismatches with our employee aliases (why revenue
// wouldn't attribute in the settlement) are obvious at a glance.
import { useEffect, useState } from 'preact/hooks';
import { getUser, groupsOf, login } from '../lib/auth';
import { apiFetch } from '../lib/api';

interface Visit {
  id: number;
  starts_at: string;
  client_name: string;
  service_name: string;
  staff_name: string | null;
  price_pln: string | null;
  status: string;
}
interface Page {
  items: Visit[];
  total: number;
}

function thisMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

const STATUS_PL: Record<string, string> = {
  completed: 'Zakończona',
  cancelled: 'Anulowana',
  no_show: 'Nieobecność',
  scheduled: 'Zaplanowana',
};

export default function VisitsBrowser() {
  const [ready, setReady] = useState(false);
  const [isStaff, setIsStaff] = useState(false);
  const [month, setMonth] = useState(thisMonth());
  const [q, setQ] = useState('');
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const user = await getUser();
      if (user && !user.expired) {
        // Browsing ALL clients' visits is admin-only; staff go to their portal.
        if (!groupsOf(user).includes('admin')) {
          window.location.replace('/panel/pracownik');
          return;
        }
        setIsStaff(true);
      }
      setReady(true);
    })();
  }, []);

  async function load() {
    setError(null);
    try {
      const params = new URLSearchParams({ month, limit: '200' });
      if (q.trim()) params.set('q', q.trim());
      setPage(await apiFetch<Page>(`/visits?${params}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (ready && isStaff) load();
  }, [ready, isStaff, month]);

  if (!ready) return <p class="muted">Ładowanie…</p>;
  if (!isStaff) {
    return (
      <div class="gate">
        <h2>Wizyty</h2>
        <p class="muted">Zaloguj się, aby kontynuować.</p>
        <button class="btn primary" onClick={() => login()}>
          Zaloguj przez Cognito
        </button>
      </div>
    );
  }

  const visits = page?.items ?? [];
  const staffNames = [...new Set(visits.map((v) => v.staff_name).filter(Boolean))] as string[];

  return (
    <div>
      <div class="bar">
        <label>
          Miesiąc:{' '}
          <input class="month" type="month" value={month} onInput={(e) => setMonth((e.target as HTMLInputElement).value)} />
        </label>
        <input
          class="search"
          type="text"
          placeholder="szukaj: klientka / usługa / pracownica"
          value={q}
          onInput={(e) => setQ((e.target as HTMLInputElement).value)}
          onKeyDown={(e) => e.key === 'Enter' && load()}
        />
        <button class="btn" onClick={load}>
          Szukaj
        </button>
      </div>
      {error && <div class="err">Błąd: {error}</div>}

      {staffNames.length > 0 && (
        <p class="staffline">
          <span class="muted small">Pracownice w Booksy (sprawdź, czy mają aliasy):</span>{' '}
          {staffNames.map((n) => (
            <span class="chip" key={n}>
              {n}
            </span>
          ))}
        </p>
      )}

      <p class="muted small">Wizyt: {page?.total ?? 0}{page && page.total > 200 ? ' (pokazano 200)' : ''}</p>

      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>Data</th>
              <th>Klientka</th>
              <th>Usługa</th>
              <th>Pracownica</th>
              <th>Kwota</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {visits.map((v) => (
              <tr key={v.id}>
                <td class="nowrap">{new Date(v.starts_at).toLocaleString('pl-PL', { dateStyle: 'short', timeStyle: 'short' })}</td>
                <td>{v.client_name}</td>
                <td>{v.service_name}</td>
                <td>{v.staff_name ?? '—'}</td>
                <td class="amt">{v.price_pln != null ? `${Number(v.price_pln).toLocaleString('pl-PL', { minimumFractionDigits: 2 })} zł` : '—'}</td>
                <td>
                  <span class={`badge s-${v.status}`}>{STATUS_PL[v.status] ?? v.status}</span>
                </td>
              </tr>
            ))}
            {visits.length === 0 && !error && (
              <tr>
                <td colSpan={6} class="muted" style="text-align:center;padding:1.5rem">
                  Brak wizyt w tym miesiącu — zsynchronizuj z Booksy.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
