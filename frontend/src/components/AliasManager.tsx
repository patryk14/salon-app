// Alias manager — maps Booksy staff names to employees so their visits credit
// revenue in the settlement. The reconciliation loop's front end: it also lists
// the month's UNMATCHED Booksy names (no alias resolves them → revenue dropped)
// and lets the owner attach each to the right employee in one click.
import { useEffect, useState } from 'preact/hooks';
import { getUser, groupsOf, login } from '../lib/auth';
import { apiFetch } from '../lib/api';

interface Alias {
  id: number;
  alias: string;
}
interface Employee {
  id: number;
  display_name: string;
  is_active: boolean;
  aliases: Alias[];
}

function thisMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

export default function AliasManager() {
  const [ready, setReady] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [month, setMonth] = useState(thisMonth());
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [unmatched, setUnmatched] = useState<string[]>([]);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
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
      // Both hit Aurora; fire together so the cold-start resume is paid once.
      const [emps, um] = await Promise.all([
        apiFetch<Employee[]>('/employees'),
        apiFetch<string[]>(`/employees/unmatched-staff?month=${month}`),
      ]);
      setEmployees(emps.filter((e) => e.is_active));
      setUnmatched(um);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (ready && isAdmin) load();
  }, [ready, isAdmin, month]);

  async function addAlias(empId: number, alias: string) {
    const name = alias.trim();
    if (!name) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/employees/${empId}/aliases`, {
        method: 'POST',
        body: JSON.stringify({ alias: name }),
      });
      setDrafts((d) => ({ ...d, [empId]: '' }));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function removeAlias(empId: number, aliasId: number) {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/employees/${empId}/aliases/${aliasId}`, { method: 'DELETE' });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!ready) return <p class="muted">Ładowanie…</p>;
  if (!isAdmin) {
    return (
      <div class="gate">
        <h2>Aliasy pracownic</h2>
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
        <a class="btn" href="/panel/wizyty">
          Wizyty
        </a>
        <span class="spacer" />
        <label>
          Sprawdź miesiąc:{' '}
          <input
            class="month"
            type="month"
            value={month}
            onInput={(e) => setMonth((e.target as HTMLInputElement).value)}
          />
        </label>
      </div>

      {error && <div class="err">Błąd: {error}</div>}

      <p class="muted small">
        Alias = imię, jakim pracownica występuje w Booksy. Bez dopasowanego aliasu jej wizyty nie
        doliczą się do przychodu w rozliczeniu.
      </p>

      {unmatched.length > 0 && (
        <div class="unmatched">
          <h2>Nazwiska z Booksy bez aliasu ({month})</h2>
          <p class="muted small">
            Te imiona pojawiły się w wizytach, ale żaden alias ich nie rozpoznaje — przychód dla nich
            przepada. Przypisz każde do pracownicy.
          </p>
          <ul class="unlist">
            {unmatched.map((name) => (
              <li key={name}>
                <span class="chip warn">{name}</span>
                <span class="assign">
                  → przypisz do:
                  <select
                    disabled={busy}
                    onChange={(e) => {
                      const id = Number((e.target as HTMLSelectElement).value);
                      (e.target as HTMLSelectElement).value = '';
                      if (id) addAlias(id, name);
                    }}
                  >
                    <option value="">— wybierz —</option>
                    {employees.map((emp) => (
                      <option value={emp.id} key={emp.id}>
                        {emp.display_name}
                      </option>
                    ))}
                  </select>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {unmatched.length === 0 && employees.length > 0 && (
        <p class="ok small">✓ Wszystkie nazwiska z Booksy w {month} mają aliasy.</p>
      )}

      {employees.length === 0 && !error && (
        <p class="muted">Budzimy serwer i wczytujemy dane… (do ~15 s po dłuższej przerwie)</p>
      )}

      <div class="cards">
        {employees.map((emp) => (
          <div class="ecard" key={emp.id}>
            <h3>{emp.display_name}</h3>
            <div class="aliases">
              {emp.aliases.length === 0 && <span class="muted small">brak aliasów</span>}
              {emp.aliases.map((a) => (
                <span class="chip" key={a.id}>
                  {a.alias}
                  <button
                    class="x"
                    title="Usuń alias"
                    disabled={busy}
                    onClick={() => removeAlias(emp.id, a.id)}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
            <div class="addrow">
              <input
                class="aliasin"
                type="text"
                placeholder="dodaj alias (imię z Booksy)"
                value={drafts[emp.id] ?? ''}
                disabled={busy}
                onInput={(e) =>
                  setDrafts((d) => ({ ...d, [emp.id]: (e.target as HTMLInputElement).value }))
                }
                onKeyDown={(e) => e.key === 'Enter' && addAlias(emp.id, drafts[emp.id] ?? '')}
              />
              <button class="mini" disabled={busy} onClick={() => addAlias(emp.id, drafts[emp.id] ?? '')}>
                dodaj
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
