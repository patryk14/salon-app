// Scheduling overview (Day 1, admin) — salon-wide availability for a month and
// the time-off requests to approve. Foundation for a future schedule generator.
import { useEffect, useState } from 'preact/hooks';
import { getUser, groupsOf, login } from '../lib/auth';
import { apiFetch } from '../lib/api';

interface Employee {
  id: number;
  display_name: string;
  is_active: boolean;
}
interface Avail {
  id: number;
  employee_id: number;
  work_date: string;
  from_time: string | null;
  to_time: string | null;
}
interface Off {
  id: number;
  employee_id: number;
  start_date: string;
  end_date: string;
  kind: string;
  status: string;
}

function thisMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}
const hhmm = (t: string | null) => (t ? t.slice(0, 5) : null);

export default function SchedulingAdmin() {
  const [ready, setReady] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [month, setMonth] = useState(thisMonth());
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [avail, setAvail] = useState<Avail[]>([]);
  const [off, setOff] = useState<Off[]>([]);
  const [error, setError] = useState<string | null>(null);

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
      const [emps, a, o] = await Promise.all([
        apiFetch<Employee[]>('/employees'),
        apiFetch<Avail[]>(`/scheduling/availability?month=${month}`),
        apiFetch<Off[]>('/scheduling/time-off'),
      ]);
      setEmployees(emps);
      setAvail(a);
      setOff(o);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (ready && isAdmin) load();
  }, [ready, isAdmin, month]);

  async function approve(id: number) {
    try {
      await apiFetch(`/scheduling/time-off/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: 'approved' }),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const nameOf = (id: number) => employees.find((e) => e.id === id)?.display_name ?? `#${id}`;

  if (!ready) return <p class="muted">Ładowanie…</p>;
  if (!isAdmin) {
    return (
      <div class="gate">
        <h2>Dyspozycyjność</h2>
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
        <a class="btn" href="/panel/dokumenty">
          Dokumenty
        </a>
        <span class="spacer" />
        <label>
          Miesiąc:{' '}
          <input class="month" type="month" value={month} onInput={(e) => setMonth((e.target as HTMLInputElement).value)} />
        </label>
      </div>

      {error && <div class="err">Błąd: {error}</div>}

      <h3>Urlopy / wolne ({off.length})</h3>
      <ul class="list">
        {off.map((o) => (
          <li key={o.id}>
            <span class="nm">
              <b>{nameOf(o.employee_id)}</b> · {o.start_date} → {o.end_date} · {o.kind}
            </span>
            {o.status === 'approved' ? (
              <span class="badge ok">zaakceptowany</span>
            ) : (
              <button class="mini" onClick={() => approve(o.id)}>
                Zaakceptuj
              </button>
            )}
          </li>
        ))}
        {off.length === 0 && <li class="muted small">Brak zgłoszeń.</li>}
      </ul>

      <h3>Dyspozycyjność w {month}</h3>
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>Data</th>
              <th>Pracownica</th>
              <th>Od–do</th>
            </tr>
          </thead>
          <tbody>
            {avail.map((a) => (
              <tr key={a.id}>
                <td class="nowrap">{a.work_date}</td>
                <td>{nameOf(a.employee_id)}</td>
                <td>{hhmm(a.from_time) ? `${hhmm(a.from_time)}–${hhmm(a.to_time) ?? '?'}` : 'cały dzień'}</td>
              </tr>
            ))}
            {avail.length === 0 && (
              <tr>
                <td colSpan={3} class="muted" style="text-align:center;padding:1.5rem">
                  Nikt nie zgłosił dyspozycyjności w tym miesiącu.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
