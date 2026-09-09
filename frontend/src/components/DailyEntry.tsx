// Daily reporting — the real source the monthly settlement is assembled from.
// Per day, per employee: hours worked (upsert) and cash-paid services (each a
// ledger entry). The monthly panel then just clicks "zassij wszystko".
import { useEffect, useState } from 'preact/hooks';
import { getUser, groupsOf, login } from '../lib/auth';
import { apiFetch } from '../lib/api';

interface Employee {
  id: number;
  display_name: string;
  is_active: boolean;
}
interface Timesheet {
  employee_id: number;
  work_date: string;
  hours: string;
}
interface LedgerRow {
  id: number;
  employee_id: number;
  amount_pln: string;
}

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
    d.getDate(),
  ).padStart(2, '0')}`;
}

const pln = (v: number) => v.toLocaleString('pl-PL', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function DailyEntry() {
  const [ready, setReady] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [day, setDay] = useState(today());
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [hours, setHours] = useState<Record<number, string>>({});
  const [cashByEmp, setCashByEmp] = useState<Record<number, number>>({});
  const [cashDraft, setCashDraft] = useState<Record<number, string>>({});
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
      const emps = await apiFetch<Employee[]>('/employees');
      const active = emps.filter((e) => e.is_active);
      setEmployees(active);

      // hours entered for this exact day
      const month = day.slice(0, 7);
      const ts = await apiFetch<Timesheet[]>(`/timesheets?month=${month}`);
      const h: Record<number, string> = {};
      ts.filter((t) => t.work_date === day).forEach((t) => (h[t.employee_id] = t.hours));
      setHours(h);

      // cash total per employee for this day
      const ledger = await apiFetch<LedgerRow[]>(`/ledger?month=${month}`);
      const c: Record<number, number> = {};
      // /ledger?month filters by month; narrow to the day would need the raw date —
      // the API returns entries with entry_date; sum only this day's is done server-side
      // via the derive; here we show the running month sum per employee as guidance.
      ledger.forEach((l) => (c[l.employee_id] = (c[l.employee_id] ?? 0) + Number(l.amount_pln)));
      setCashByEmp(c);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (ready && isAdmin) load();
  }, [ready, isAdmin, day]);

  async function saveHours(empId: number, value: string) {
    try {
      await apiFetch('/timesheets', {
        method: 'POST',
        body: JSON.stringify({ employee_id: empId, work_date: day, hours: value === '' ? '0' : value }),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function addCash(empId: number) {
    const amount = cashDraft[empId];
    if (!amount || Number(amount) <= 0) return;
    try {
      await apiFetch('/ledger', {
        method: 'POST',
        body: JSON.stringify({ employee_id: empId, entry_date: day, amount_pln: amount }),
      });
      setCashDraft((d) => ({ ...d, [empId]: '' }));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  if (!ready) return <p class="muted">Ładowanie…</p>;
  if (!isAdmin) {
    return (
      <div class="gate">
        <h2>Raport dzienny</h2>
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
        <label>
          Dzień:{' '}
          <input class="month" type="date" value={day} onInput={(e) => setDay((e.target as HTMLInputElement).value)} />
        </label>
      </div>
      {error && <div class="err">Błąd: {error}</div>}
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>Pracownica</th>
              <th>Godziny (dzień)</th>
              <th>Gotówka — dodaj wpis</th>
              <th>Gotówka w miesiącu</th>
            </tr>
          </thead>
          <tbody>
            {employees.map((emp) => (
              <tr key={emp.id}>
                <td class="name">{emp.display_name}</td>
                <td>
                  <input
                    class="cell"
                    type="text"
                    inputMode="decimal"
                    placeholder="0"
                    value={hours[emp.id] ?? ''}
                    onBlur={(e) => saveHours(emp.id, (e.target as HTMLInputElement).value)}
                  />
                </td>
                <td>
                  <input
                    class="cell"
                    type="text"
                    inputMode="decimal"
                    placeholder="kwota"
                    value={cashDraft[emp.id] ?? ''}
                    onInput={(e) => setCashDraft((d) => ({ ...d, [emp.id]: (e.target as HTMLInputElement).value }))}
                  />
                  <button class="mini" onClick={() => addCash(emp.id)}>
                    dodaj
                  </button>
                </td>
                <td class="out">{pln(cashByEmp[emp.id] ?? 0)} zł</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p class="muted small" style="margin-top:.8rem">
        Godziny zapisują się po wyjściu z pola (jeden wpis na dzień). Gotówka to osobne wpisy —
        każdy „dodaj" to jedna kwota. Sumy trafiają do rozliczenia po „Zassij wszystko".
      </p>
    </div>
  );
}
