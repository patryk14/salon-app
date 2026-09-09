// Daily reporting — the real source the monthly settlement is assembled from.
// Per day, per employee: hours worked (upsert), cash-paid services (ledger),
// and prepaid package/voucher visits (notebook). The monthly panel then just
// clicks "zassij wszystko".
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
interface Amount {
  employee_id: number;
  amount_pln: string;
}

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
    d.getDate(),
  ).padStart(2, '0')}`;
}

const pln = (v: number) =>
  v.toLocaleString('pl-PL', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function DailyEntry() {
  const [ready, setReady] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [day, setDay] = useState(today());
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [hours, setHours] = useState<Record<number, string>>({});
  const [cashMonth, setCashMonth] = useState<Record<number, number>>({});
  const [nbMonth, setNbMonth] = useState<Record<number, number>>({});
  const [cashDraft, setCashDraft] = useState<Record<number, string>>({});
  const [cashName, setCashName] = useState<Record<number, string>>({});
  const [nbAmount, setNbAmount] = useState<Record<number, string>>({});
  const [nbName, setNbName] = useState<Record<number, string>>({});
  const [services, setServices] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const MAX_HOURS = 11;

  useEffect(() => {
    (async () => {
      const user = await getUser();
      if (user && !user.expired) setIsAdmin(groupsOf(user).includes('admin'));
      setReady(true);
    })();
  }, []);

  async function load() {
    setError(null);
    const month = day.slice(0, 7);
    try {
      const [emps, ts, ledger, nb, svc] = await Promise.all([
        apiFetch<Employee[]>('/employees'),
        apiFetch<Timesheet[]>(`/timesheets?month=${month}`),
        apiFetch<Amount[]>(`/ledger?month=${month}`),
        apiFetch<Amount[]>(`/notebook?month=${month}`),
        apiFetch<string[]>('/services'),
      ]);
      setEmployees(emps.filter((e) => e.is_active));
      setServices(svc);

      const h: Record<number, string> = {};
      ts.filter((t) => t.work_date === day).forEach((t) => (h[t.employee_id] = t.hours));
      setHours(h);

      const sum = (rows: Amount[]) => {
        const acc: Record<number, number> = {};
        rows.forEach((r) => (acc[r.employee_id] = (acc[r.employee_id] ?? 0) + Number(r.amount_pln)));
        return acc;
      };
      setCashMonth(sum(ledger));
      setNbMonth(sum(nb));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (ready && isAdmin) load();
  }, [ready, isAdmin, day]);

  async function saveHours(empId: number, value: string) {
    if (value !== '' && Number(value) > MAX_HOURS) {
      setError(`Maksymalnie ${MAX_HOURS} godzin na dzień — sprawdź wpis.`);
      await load(); // reset the field to the stored value
      return;
    }
    setError(null);
    try {
      await apiFetch('/timesheets', {
        method: 'POST',
        body: JSON.stringify({
          employee_id: empId,
          work_date: day,
          hours: value === '' ? '0' : value,
        }),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function addCash(empId: number) {
    const amount = cashDraft[empId];
    const name = cashName[empId];
    if (!amount || Number(amount) <= 0) return;
    if (!name || !name.trim()) {
      setError('Podaj rodzaj usługi dla wpisu gotówkowego.');
      return;
    }
    try {
      await apiFetch('/ledger', {
        method: 'POST',
        body: JSON.stringify({
          employee_id: empId,
          entry_date: day,
          service_name: name,
          amount_pln: amount,
        }),
      });
      setCashDraft((d) => ({ ...d, [empId]: '' }));
      setCashName((d) => ({ ...d, [empId]: '' }));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function addNotebook(empId: number) {
    const amount = nbAmount[empId];
    const name = nbName[empId] || 'Pakiet / voucher';
    if (!amount || Number(amount) <= 0) return;
    try {
      await apiFetch('/notebook', {
        method: 'POST',
        body: JSON.stringify({
          employee_id: empId,
          entry_date: day,
          service_name: name,
          amount_pln: amount,
        }),
      });
      setNbAmount((d) => ({ ...d, [empId]: '' }));
      setNbName((d) => ({ ...d, [empId]: '' }));
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
          <input
            class="month"
            type="date"
            value={day}
            onInput={(e) => setDay((e.target as HTMLInputElement).value)}
          />
        </label>
      </div>
      {error && <div class="err">Błąd: {error}</div>}
      {employees.length === 0 && !error && (
        <p class="muted">Budzimy serwer i wczytujemy dane… (do ~15 s po dłuższej przerwie)</p>
      )}
      <datalist id="booksy-services">
        {services.map((s) => (
          <option key={s} value={s} />
        ))}
      </datalist>
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>Pracownica</th>
              <th>Godziny (≤ {MAX_HOURS})</th>
              <th>Gotówka — dodaj</th>
              <th>Zeszyt (pakiet) — dodaj</th>
              <th>Gotówka / zeszyt (mies.)</th>
            </tr>
          </thead>
          <tbody>
            {employees.map((emp) => (
              <tr key={emp.id}>
                <td class="name">{emp.display_name}</td>
                <td>
                  <input
                    class="cell narrow"
                    type="text"
                    inputMode="decimal"
                    placeholder="0"
                    value={hours[emp.id] ?? ''}
                    onBlur={(e) => saveHours(emp.id, (e.target as HTMLInputElement).value)}
                  />
                </td>
                <td>
                  <input
                    class="cell name-in"
                    type="text"
                    list="booksy-services"
                    placeholder="usługa"
                    value={cashName[emp.id] ?? ''}
                    onInput={(e) =>
                      setCashName((d) => ({ ...d, [emp.id]: (e.target as HTMLInputElement).value }))
                    }
                  />
                  <input
                    class="cell narrow"
                    type="text"
                    inputMode="decimal"
                    placeholder="kwota"
                    value={cashDraft[emp.id] ?? ''}
                    onInput={(e) =>
                      setCashDraft((d) => ({ ...d, [emp.id]: (e.target as HTMLInputElement).value }))
                    }
                  />
                  <button class="mini" onClick={() => addCash(emp.id)}>
                    dodaj
                  </button>
                </td>
                <td>
                  <input
                    class="cell name-in"
                    type="text"
                    list="booksy-services"
                    placeholder="usługa"
                    value={nbName[emp.id] ?? ''}
                    onInput={(e) =>
                      setNbName((d) => ({ ...d, [emp.id]: (e.target as HTMLInputElement).value }))
                    }
                  />
                  <input
                    class="cell narrow"
                    type="text"
                    inputMode="decimal"
                    placeholder="wartość"
                    value={nbAmount[emp.id] ?? ''}
                    onInput={(e) =>
                      setNbAmount((d) => ({ ...d, [emp.id]: (e.target as HTMLInputElement).value }))
                    }
                  />
                  <button class="mini" onClick={() => addNotebook(emp.id)}>
                    dodaj
                  </button>
                </td>
                <td class="out">
                  {pln(cashMonth[emp.id] ?? 0)} / {pln(nbMonth[emp.id] ?? 0)} zł
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p class="muted small" style="margin-top:.8rem">
        Godziny zapisują się po wyjściu z pola (jeden wpis na dzień). Gotówka i zeszyt to osobne
        wpisy — każdy „dodaj" to jedna kwota. <b>Zeszyt</b> = wizyta opłacona z góry (pakiet/voucher),
        Booksy rozliczy ją na 0 zł, ale prowizję dostaje wykonawczyni. Sumy trafiają do rozliczenia po
        „Zassij wszystko".
      </p>
    </div>
  );
}
