// Packages (admin) — client packages synced from Booksy: who holds what, how
// many treatments are left, when it expires, and the per-treatment value that
// feeds commission on redemption. Read-only; Booksy is the source of truth.
import { useEffect, useState } from 'preact/hooks';
import { getUser, groupsOf, login } from '../lib/auth';
import { apiFetch } from '../lib/api';

interface Pkg {
  id: number;
  client_name: string;
  name: string;
  total_value: string;
  total_treatments: number;
  remaining: number;
  used: number;
  value_per_treatment: string;
  valid_until: string | null;
  status: string;
}

const pln = (v: string) => Number(v).toLocaleString('pl-PL', { maximumFractionDigits: 0 });
const STATUS_PL: Record<string, string> = {
  active: 'aktywny',
  used_up: 'wykorzystany',
  expired: 'wygasły',
};

export default function PackagesView() {
  const [ready, setReady] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [rows, setRows] = useState<Pkg[]>([]);
  const [error, setError] = useState<string | null>(null);

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
      setRows(await apiFetch<Pkg[]>('/packages'));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (ready && isAdmin) load();
  }, [ready, isAdmin]);

  if (!ready) return <p class="muted">Ładowanie…</p>;
  if (!isAdmin) {
    return (
      <div class="gate">
        <h2>Pakiety</h2>
        <p class="muted">Zaloguj się, aby kontynuować.</p>
        <button class="btn primary" onClick={() => login()}>
          Zaloguj przez Cognito
        </button>
      </div>
    );
  }

  const active = rows.filter((r) => r.status === 'active');
  return (
    <div>
      {error && <div class="err">Błąd: {error}</div>}
      <p class="muted small">
        Synchronizowane z Booksy (źródło prawdy). Prowizja za realizację = wartość / liczba zabiegów.
        Sync na ekranie „Synchronizacja Booksy".
      </p>
      <p class="muted small">
        Aktywnych: <b>{active.length}</b> · wszystkich: <b>{rows.length}</b>
      </p>
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>Klientka</th>
              <th>Pakiet</th>
              <th>Wart./zabieg</th>
              <th>Zostało</th>
              <th>Ważny do</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id}>
                <td>{p.client_name}</td>
                <td>{p.name}</td>
                <td class="amt">{pln(p.value_per_treatment)} zł</td>
                <td class="amt">
                  <b>{p.remaining}</b> / {p.total_treatments}
                </td>
                <td class="nowrap">{p.valid_until ?? '—'}</td>
                <td>
                  <span class={`badge s-${p.status}`}>{STATUS_PL[p.status] ?? p.status}</span>
                </td>
              </tr>
            ))}
            {rows.length === 0 && !error && (
              <tr>
                <td colSpan={6} class="muted" style="text-align:center;padding:1.5rem">
                  Brak pakietów — zsynchronizuj z Booksy.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
