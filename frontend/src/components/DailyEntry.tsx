// Daily reporting — the real source the monthly settlement is assembled from.
// One card per employee (stacks on any width — no wide table to overflow):
//   hours (upsert, ≤11), and cash + notebook sections that LIST the day's
//   entries with a delete button, so a wrong amount is fixed by removing it and
//   adding the correct one. Service names autocomplete from the Booksy catalog.
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
interface Entry {
  id: number;
  employee_id: number;
  entry_date: string;
  service_name: string | null;
  amount_pln: string;
}
interface SalonDay {
  day: string;
  booksy_cash: string;
  fiscal_register: string;
  unregistered_cash: string;
  cash_in_register: string;
  note: string | null;
}

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
    d.getDate(),
  ).padStart(2, '0')}`;
}
const pln = (v: number | string) =>
  Number(v).toLocaleString('pl-PL', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const MAX_HOURS = 11;

export default function DailyEntry() {
  const [ready, setReady] = useState(false);
  const [allowed, setAllowed] = useState(false); // staff OR admin may reconcile a day
  const [admin, setAdmin] = useState(false); // only admins get the admin nav / back to /panel
  const [day, setDay] = useState(today());
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [hours, setHours] = useState<Record<number, string>>({});
  const [ledger, setLedger] = useState<Entry[]>([]);
  const [notebook, setNotebook] = useState<Entry[]>([]);
  const [services, setServices] = useState<string[]>([]);
  // drafts keyed "cash-<empId>" / "nb-<empId>"
  const [name, setName] = useState<Record<string, string>>({});
  const [amount, setAmount] = useState<Record<string, string>>({});
  const [cash, setCash] = useState<SalonDay | null>(null);
  const [booksyIn, setBooksyIn] = useState('');
  const [fiscalIn, setFiscalIn] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const user = await getUser();
      if (user && !user.expired) {
        const g = groupsOf(user);
        // Daily reconciliation is front-desk work: staff AND admin. Anonymous
        // visitors fall through to a neutral login gate below.
        if (g.includes('staff') || g.includes('admin')) {
          setAllowed(true);
          setAdmin(g.includes('admin'));
        }
      }
      setReady(true);
    })();
  }, []);

  async function load() {
    setError(null);
    const month = day.slice(0, 7);
    try {
      const [emps, ts, led, nb, svc, sd] = await Promise.all([
        apiFetch<Employee[]>('/employees'),
        apiFetch<Timesheet[]>(`/timesheets?month=${month}`),
        apiFetch<Entry[]>(`/ledger?month=${month}`),
        apiFetch<Entry[]>(`/notebook?month=${month}`),
        apiFetch<string[]>('/services'),
        apiFetch<SalonDay>(`/salon-days/${day}`),
      ]);
      setEmployees(emps.filter((e) => e.is_active));
      setServices(svc);
      setLedger(led);
      setNotebook(nb);
      setCash(sd);
      setBooksyIn(Number(sd.booksy_cash) ? sd.booksy_cash : '');
      setFiscalIn(Number(sd.fiscal_register) ? sd.fiscal_register : '');
      const h: Record<number, string> = {};
      ts.filter((t) => t.work_date === day).forEach((t) => (h[t.employee_id] = t.hours));
      setHours(h);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (ready && allowed) load();
  }, [ready, allowed, day]);

  const forDay = (rows: Entry[], empId: number) =>
    rows.filter((r) => r.employee_id === empId && r.entry_date === day);
  const monthSum = (rows: Entry[], empId: number) =>
    rows.filter((r) => r.employee_id === empId).reduce((s, r) => s + Number(r.amount_pln), 0);

  async function saveHours(empId: number, value: string) {
    if (value !== '' && Number(value) > MAX_HOURS) {
      setError(`Maksymalnie ${MAX_HOURS} godzin na dzień — sprawdź wpis.`);
      await load();
      return;
    }
    setError(null);
    try {
      await apiFetch('/timesheets', {
        method: 'POST',
        body: JSON.stringify({ employee_id: empId, work_date: day, hours: value === '' ? '0' : value }),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function addEntry(kind: 'cash' | 'nb', empId: number) {
    const key = `${kind}-${empId}`;
    const amt = amount[key];
    const svc = (name[key] ?? '').trim();
    if (!amt || Number(amt) <= 0) return;
    if (!svc) {
      setError('Podaj rodzaj usługi.');
      return;
    }
    try {
      const path = kind === 'cash' ? '/ledger' : '/notebook';
      await apiFetch(path, {
        method: 'POST',
        body: JSON.stringify({
          employee_id: empId,
          entry_date: day,
          service_name: svc,
          amount_pln: amt,
        }),
      });
      setName((d) => ({ ...d, [key]: '' }));
      setAmount((d) => ({ ...d, [key]: '' }));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function removeEntry(kind: 'cash' | 'nb', id: number) {
    try {
      await apiFetch(`${kind === 'cash' ? '/ledger' : '/notebook'}/${id}`, { method: 'DELETE' });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function saveCash() {
    setError(null);
    try {
      await apiFetch(`/salon-days/${day}`, {
        method: 'PUT',
        body: JSON.stringify({
          booksy_cash: booksyIn === '' ? '0' : booksyIn,
          fiscal_register: fiscalIn === '' ? '0' : fiscalIn,
        }),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  if (!ready) return <p class="muted">Ładowanie…</p>;
  if (!allowed) {
    return (
      <div class="gate">
        <h2>Raport dzienny</h2>
        <p class="muted">Zaloguj się, aby kontynuować.</p>
        <button class="btn primary" onClick={() => login()}>
          Zaloguj przez Cognito
        </button>
      </div>
    );
  }

  function section(kind: 'cash' | 'nb', emp: Employee, rows: Entry[], label: string) {
    const key = `${kind}-${emp.id}`;
    const entries = forDay(rows, emp.id);
    return (
      <div class="sect">
        <div class="secthead">
          {label}
          <span class="sum">miesiąc: {pln(monthSum(rows, emp.id))} zł</span>
        </div>
        {entries.length > 0 && (
          <ul class="entries">
            {entries.map((e) => (
              <li key={e.id}>
                <span class="svc">{e.service_name ?? '—'}</span>
                <span class="amt">{pln(e.amount_pln)} zł</span>
                <button class="del" title="Usuń wpis" onClick={() => removeEntry(kind, e.id)}>
                  usuń
                </button>
              </li>
            ))}
          </ul>
        )}
        <div class="addrow">
          <input
            class="fld svc-in"
            type="text"
            list="booksy-services"
            placeholder="usługa"
            value={name[key] ?? ''}
            onInput={(ev) => setName((d) => ({ ...d, [key]: (ev.target as HTMLInputElement).value }))}
          />
          <input
            class="fld amt-in"
            type="text"
            inputMode="decimal"
            placeholder="kwota"
            value={amount[key] ?? ''}
            onInput={(ev) => setAmount((d) => ({ ...d, [key]: (ev.target as HTMLInputElement).value }))}
          />
          <button class="btn small" onClick={() => addEntry(kind, emp.id)}>
            dodaj
          </button>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div class="bar">
        {!admin && (
          <a class="btn" href="/panel/pracownik">
            ← Mój portal
          </a>
        )}
        <label>
          Dzień:{' '}
          <input class="month" type="date" value={day} onInput={(e) => setDay((e.target as HTMLInputElement).value)} />
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

      <div class="cards">
        {employees.map((emp) => (
          <div class="empcard" key={emp.id}>
            <div class="cardhead">
              <span class="empname">{emp.display_name}</span>
              <label class="hours">
                godziny (≤{MAX_HOURS}):{' '}
                <input
                  class="fld hours-in"
                  type="text"
                  inputMode="decimal"
                  placeholder="0"
                  value={hours[emp.id] ?? ''}
                  onBlur={(e) => saveHours(emp.id, (e.target as HTMLInputElement).value)}
                />
              </label>
            </div>
            {section('cash', emp, ledger, 'Gotówka')}
            {section('nb', emp, notebook, 'Zeszyt (pakiet / voucher)')}
          </div>
        ))}
      </div>

      {employees.length > 0 && (
        <div class="kasa">
          <h3>Kasa dnia — {day}</h3>
          <div class="kasarow">
            <div class="kfield">
              <span class="klbl">Gotówka nie wbita</span>
              <span class="kval">{pln(cash?.unregistered_cash ?? 0)} zł</span>
              <span class="khint">liczone z wpisów gotówki</span>
            </div>
            <div class="kfield">
              <span class="klbl">Gotówka z Booksy</span>
              <input
                class="fld kin"
                type="text"
                inputMode="decimal"
                placeholder="0"
                value={booksyIn}
                onInput={(e) => setBooksyIn((e.target as HTMLInputElement).value)}
              />
            </div>
            <div class="kfield">
              <span class="klbl">Suma gotówki w kasie</span>
              <span class="kval">
                {pln(Number(cash?.unregistered_cash ?? 0) + Number(booksyIn || 0))} zł
              </span>
              <span class="khint">nie wbita + Booksy</span>
            </div>
            <div class="kfield">
              <span class="klbl">Kasa fiskalna</span>
              <input
                class="fld kin"
                type="text"
                inputMode="decimal"
                placeholder="0"
                value={fiscalIn}
                onInput={(e) => setFiscalIn((e.target as HTMLInputElement).value)}
              />
            </div>
            <button class="btn" onClick={saveCash}>
              Zapisz kasę
            </button>
          </div>
        </div>
      )}

      <p class="muted small" style="margin-top:1rem">
        Godziny zapisują się po wyjściu z pola (jeden wpis na dzień, max {MAX_HOURS}). Gotówka i zeszyt
        to osobne wpisy — błędny usuń i dodaj poprawny. <b>Zeszyt</b> = wizyta opłacona z góry, Booksy
        rozliczy ją na 0 zł, ale prowizję dostaje wykonawczyni. Sumy trafiają do rozliczenia po „Zassij
        wszystko".
      </p>
    </div>
  );
}
