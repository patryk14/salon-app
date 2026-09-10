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
interface Invite {
  id: number;
  code: string;
  employee_id: number | null;
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

  useEffect(() => {
    (async () => {
      const user = await getUser();
      if (user && !user.expired) setIsAdmin(groupsOf(user).includes('admin'));
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

  const nameOf = (id: number | null) =>
    employees.find((e) => e.id === id)?.display_name ?? `#${id}`;

  if (!ready) return <p class="muted">Ładowanie…</p>;
  if (!isAdmin) {
    return (
      <div class="gate">
        <h2>Konta pracownic</h2>
        <p class="muted">Zaloguj się kontem właścicielki.</p>
        <button class="btn primary" onClick={() => login()}>
          Zaloguj przez Cognito
        </button>
      </div>
    );
  }

  return (
    <div>
      <div class="bar">
        <a class="btn" href="/panel">
          ← Rozliczenia
        </a>
        <a class="btn" href="/panel/aliasy">
          Aliasy
        </a>
      </div>

      {error && <div class="err">Błąd: {error}</div>}

      {fresh && (
        <div class="freshbox">
          Nowy kod zaproszenia: <span class="code">{fresh}</span>
          <span class="muted small"> — przekaż go pracownicy. Ważny 14 dni, jednorazowy.</span>
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

      {invites.length > 0 && (
        <>
          <h3>Kody</h3>
          <div class="scroll">
            <table>
              <thead>
                <tr>
                  <th>Kod</th>
                  <th>Pracownica</th>
                  <th>Wygasa</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {invites.map((inv) => (
                  <tr key={inv.id}>
                    <td class="code">{inv.code}</td>
                    <td>{nameOf(inv.employee_id)}</td>
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
