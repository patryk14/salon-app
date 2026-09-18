// Invite manager (F6, admin) — create a one-time code for an employee and hand
// it to them in the salon. They enter it in the staff portal to link their
// Cognito login to their profile. Shows the codes and whether each was claimed.
import { useEffect, useState } from 'preact/hooks';
import { getUser, groupsOf, login } from '../lib/auth';
import { apiFetch } from '../lib/api';

interface Employee {
  id: number;
  display_name: string;
  is_active: boolean;
}
interface Client {
  id: number;
  first_name: string;
  last_name: string;
  phone: string | null;
}
interface Invite {
  id: number;
  code: string;
  role: string;
  employee_id: number | null;
  client_id: number | null;
  expires_at: string | null;
  claimed_at: string | null;
}

export default function InviteManager() {
  const [ready, setReady] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [fresh, setFresh] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [clientQ, setClientQ] = useState('');
  const [clientResults, setClientResults] = useState<Client[]>([]);

  useEffect(() => {
    (async () => {
      const user = await getUser();
      if (user && !user.expired) {
        // Staff must never see admin pages, nor that admin exists — bounce them
        // to their own portal. Anonymous visitors fall through to a neutral login.
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
      const [emps, inv] = await Promise.all([
        apiFetch<Employee[]>('/employees'),
        apiFetch<Invite[]>('/invites'),
      ]);
      setEmployees(emps.filter((e) => e.is_active));
      setInvites(inv);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (ready && isAdmin) load();
  }, [ready, isAdmin]);

  async function createInvite(employeeId: number) {
    setBusy(true);
    setError(null);
    try {
      const inv = await apiFetch<Invite>('/invites', {
        method: 'POST',
        body: JSON.stringify({ employee_id: employeeId }),
      });
      setFresh(inv.code);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function searchClients(e: Event) {
    e.preventDefault();
    if (!clientQ.trim()) return;
    setError(null);
    try {
      const page = await apiFetch<{ items: Client[] }>(
        `/clients?q=${encodeURIComponent(clientQ.trim())}&limit=20`,
      );
      setClientResults(page.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function createClientInvite(clientId: number) {
    setBusy(true);
    setError(null);
    try {
      const inv = await apiFetch<Invite>('/invites', {
        method: 'POST',
        body: JSON.stringify({ client_id: clientId }),
      });
      setFresh(inv.code);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const nameOf = (id: number | null) =>
    employees.find((e) => e.id === id)?.display_name ?? `#${id}`;
  const targetOf = (inv: Invite) =>
    inv.role === 'client' ? `Klientka #${inv.client_id}` : nameOf(inv.employee_id);

  if (!ready) return <p class="muted">Ładowanie…</p>;
  if (!isAdmin) {
    return (
      <div class="gate">
        <h2>Konta pracownic</h2>
        <p class="muted">Zaloguj się, aby kontynuować.</p>
        <button class="btn primary" onClick={() => login()}>
          Zaloguj przez Cognito
        </button>
      </div>
    );
  }

  return (
    <div>

      {error && <div class="err">Błąd: {error}</div>}

      {fresh && (
        <div class="freshbox">
          Nowy kod zaproszenia: <span class="code">{fresh}</span>
          <span class="muted small"> — przekaż osobie. Ważny 14 dni, jednorazowy.</span>
        </div>
      )}

      <p class="muted small">
        Najpierw utwórz pracownicy konto w Cognito (grupa <code>staff</code>), potem wygeneruj tu kod
        — wpisze go w portalu, żeby połączyć logowanie ze swoim profilem.
      </p>

      <h3>Pracownice</h3>
      <div class="cards">
        {employees.map((emp) => (
          <div class="ecard" key={emp.id}>
            <span class="name">{emp.display_name}</span>
            <button class="mini" disabled={busy} onClick={() => createInvite(emp.id)}>
              Utwórz kod
            </button>
          </div>
        ))}
      </div>

      <h3>Klientki</h3>
      <p class="muted small">
        Wyszukaj klientkę (imię/nazwisko/telefon) i wygeneruj kod — wpisze go w „Mój profil"
        (<code>/klient</code>), żeby widzieć swoje wizyty, pakiety i vouchery.
      </p>
      <form class="row" onSubmit={searchClients}>
        <input
          placeholder="Szukaj klientki…"
          value={clientQ}
          onInput={(e) => setClientQ((e.target as HTMLInputElement).value)}
        />
        <button class="mini" type="submit">
          Szukaj
        </button>
      </form>
      {clientResults.length > 0 && (
        <div class="cards">
          {clientResults.map((c) => (
            <div class="ecard" key={c.id}>
              <span class="name">
                {c.first_name} {c.last_name}
                {c.phone ? <span class="muted small"> · {c.phone}</span> : null}
              </span>
              <button class="mini" disabled={busy} onClick={() => createClientInvite(c.id)}>
                Utwórz kod
              </button>
            </div>
          ))}
        </div>
      )}

      {invites.length > 0 && (
        <>
          <h3>Kody</h3>
          <div class="scroll">
            <table>
              <thead>
                <tr>
                  <th>Kod</th>
                  <th>Kto</th>
                  <th>Wygasa</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {invites.map((inv) => (
                  <tr key={inv.id}>
                    <td class="code">{inv.code}</td>
                    <td>{targetOf(inv)}</td>
                    <td class="nowrap">
                      {inv.expires_at
                        ? new Date(inv.expires_at).toLocaleDateString('pl-PL')
                        : '—'}
                    </td>
                    <td>
                      {inv.claimed_at ? (
                        <span class="badge ok">Powiązany</span>
                      ) : (
                        <span class="badge wait">Oczekuje</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
