// Staff portal (F6) — an employee's OWN view: schedule, merged revenue, a live
// commission preview and self-entry of hours. Everything is row-scoped by the
// backend to the token's employee (the /me/* endpoints); this UI never sends an
// employee id. Before the account is linked it shows the invite-claim box.
import { useEffect, useState } from 'preact/hooks';
import { getUser, groupsOf, login, logout } from '../lib/auth';
import { apiFetch } from '../lib/api';

interface Link {
  linked: boolean;
  role: string;
  employee_id: number | null;
  display_name: string | null;
  fte_factor: string | null;
  pay_type: string | null;
  is_active: boolean | null;
}
interface Revenue {
  booksy_services: string;
  cash_services: string;
  notebook_services: string;
  services_total: string;
}
interface Commission {
  services_base: string;
  services_rate: string;
  services_commission: string;
  sales_commission: string;
  hours: string;
  hours_pay: string;
  total_payout: string;
}
interface Visit {
  id: number;
  starts_at: string;
  client_name: string;
  service_name: string;
  price_pln: string | null;
  status: string;
}
interface Hours {
  id: number;
  work_date: string;
  hours: string;
  note: string | null;
}
interface Doc {
  id: number;
  doc_type: string;
  title: string | null;
  valid_until: string | null;
}
interface Avail {
  id: number;
  work_date: string;
  from_time: string | null;
  to_time: string | null;
}
interface Off {
  id: number;
  start_date: string;
  end_date: string;
  kind: string;
  status: string;
}

const pln = (v: string, dec = 0) =>
  Number(v).toLocaleString('pl-PL', { minimumFractionDigits: dec, maximumFractionDigits: dec });

const STATUS_PL: Record<string, string> = {
  completed: 'Zakończona',
  cancelled: 'Anulowana',
  no_show: 'Nieobecność',
  scheduled: 'Zaplanowana',
};

function thisMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

// Default every date field to today (local), so entry is one calendar click, not
// typing. `YYYY-MM-DD` in local time (toISOString would shift across midnight UTC).
function todayISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export default function StaffPortal() {
  const [ready, setReady] = useState(false);
  const [isStaff, setIsStaff] = useState(false);
  const [link, setLink] = useState<Link | null>(null);
  const [month, setMonth] = useState(thisMonth());
  const [revenue, setRevenue] = useState<Revenue | null>(null);
  const [commission, setCommission] = useState<Commission | null>(null);
  const [visits, setVisits] = useState<Visit[]>([]);
  const [hours, setHours] = useState<Hours[]>([]);
  const [code, setCode] = useState('');
  const [hDate, setHDate] = useState(todayISO());
  const [hVal, setHVal] = useState('');
  const [services, setServices] = useState<string[]>([]);
  const [cDate, setCDate] = useState(todayISO());
  const [cService, setCService] = useState('');
  const [cVal, setCVal] = useState('');
  const [nDate, setNDate] = useState(todayISO());
  const [nService, setNService] = useState('');
  const [nVal, setNVal] = useState('');
  const [docs, setDocs] = useState<Doc[]>([]);
  const [avail, setAvail] = useState<Avail[]>([]);
  const [off, setOff] = useState<Off[]>([]);
  const [aDate, setADate] = useState(todayISO());
  const [oStart, setOStart] = useState(todayISO());
  const [oEnd, setOEnd] = useState(todayISO());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      const user = await getUser();
      if (user && !user.expired) {
        const g = groupsOf(user);
        setIsStaff(g.includes('staff') || g.includes('admin'));
      }
      setReady(true);
    })();
  }, []);

  async function loadLink() {
    setError(null);
    try {
      setLink(await apiFetch<Link>('/me'));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (ready && isStaff) loadLink();
  }, [ready, isStaff]);

  async function loadMonth() {
    if (!link?.linked) return;
    setError(null);
    try {
      const [rev, com, vis, hrs, svc, dcs, avl, ofs] = await Promise.all([
        apiFetch<Revenue>(`/me/revenue?month=${month}`),
        apiFetch<Commission>(`/me/commission?month=${month}`),
        apiFetch<Visit[]>(`/me/visits?month=${month}`),
        apiFetch<Hours[]>(`/me/hours?month=${month}`),
        apiFetch<string[]>('/services'),
        apiFetch<Doc[]>('/me/documents'),
        apiFetch<Avail[]>(`/me/availability?month=${month}`),
        apiFetch<Off[]>('/me/time-off'),
      ]);
      setRevenue(rev);
      setCommission(com);
      setVisits(vis);
      setHours(hrs);
      setServices(svc);
      setDocs(dcs);
      setAvail(avl);
      setOff(ofs);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (link?.linked) loadMonth();
  }, [link?.linked, month]);

  async function claim() {
    if (!code.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch('/invites/claim', {
        method: 'POST',
        body: JSON.stringify({ code: code.trim() }),
      });
      setCode('');
      await loadLink();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function addHours() {
    if (!hDate || !hVal) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch('/me/hours', {
        method: 'POST',
        body: JSON.stringify({ work_date: hDate, hours: hVal }),
      });
      setHVal('');
      await loadMonth();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function addCash() {
    if (!cDate || !cService.trim() || !cVal) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch('/me/cash', {
        method: 'POST',
        body: JSON.stringify({
          entry_date: cDate,
          service_name: cService.trim(),
          amount_pln: cVal,
        }),
      });
      setCService('');
      setCVal('');
      await loadMonth(); // refresh the revenue tile
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function addNotebook() {
    if (!nDate || !nService.trim() || !nVal) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch('/me/notebook', {
        method: 'POST',
        body: JSON.stringify({
          entry_date: nDate,
          service_name: nService.trim(),
          amount_pln: nVal,
        }),
      });
      setNService('');
      setNVal('');
      await loadMonth();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveAction(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await loadMonth();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const addAvailability = () =>
    aDate &&
    saveAction(() =>
      apiFetch('/me/availability', { method: 'POST', body: JSON.stringify({ work_date: aDate }) }),
    );
  const delAvailability = (id: number) =>
    saveAction(() => apiFetch(`/me/availability/${id}`, { method: 'DELETE' }));
  const addTimeOff = () =>
    oStart &&
    oEnd &&
    saveAction(async () => {
      await apiFetch('/me/time-off', {
        method: 'POST',
        body: JSON.stringify({ start_date: oStart, end_date: oEnd }),
      });
      setOStart('');
      setOEnd('');
    });
  const delTimeOff = (id: number) =>
    saveAction(() => apiFetch(`/me/time-off/${id}`, { method: 'DELETE' }));

  if (!ready) return <p class="muted">Ładowanie…</p>;

  if (!isStaff) {
    return (
      <div class="gate">
        <h2>Portal pracownicy</h2>
        <p class="muted">Zaloguj się swoim kontem, aby zobaczyć swój grafik i utarg.</p>
        <button class="btn primary" onClick={() => login()}>
          Zaloguj przez Cognito
        </button>
      </div>
    );
  }

  if (link && !link.linked) {
    return (
      <div>
        <div class="bar">
          <span class="muted">Zalogowano — konto nie jest jeszcze powiązane z pracownicą.</span>
          <span class="spacer" />
          <button class="btn" onClick={() => logout()}>
            Wyloguj
          </button>
        </div>
        {error && <div class="err">Błąd: {error}</div>}
        <div class="gate">
          <h2>Wpisz kod zaproszenia</h2>
          <p class="muted">
            Właścicielka przekazała Ci jednorazowy kod. Wpisz go, aby połączyć konto ze swoim
            profilem.
          </p>
          <input
            class="codein"
            type="text"
            placeholder="np. ABCD2345"
            value={code}
            disabled={busy}
            onInput={(e) => setCode((e.target as HTMLInputElement).value.toUpperCase())}
            onKeyDown={(e) => e.key === 'Enter' && claim()}
          />
          <button class="btn primary" disabled={busy} onClick={claim}>
            Połącz konto
          </button>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div class="bar">
        <b>{link?.display_name}</b>
        <label>
          Miesiąc:{' '}
          <input
            class="month"
            type="month"
            value={month}
            onInput={(e) => setMonth((e.target as HTMLInputElement).value)}
          />
        </label>
        <a class="btn" href="/panel/dzien">
          Rozliczenie dnia
        </a>
        <a class="btn" href="/panel/zaopatrzenie">
          Lista zamówień
        </a>
        <span class="spacer" />
        <button class="btn" onClick={() => logout()}>
          Wyloguj
        </button>
      </div>

      {error && <div class="err">Błąd: {error}</div>}

      <div class="cards">
        <div class="stat">
          <span class="lbl">Utarg (usługi)</span>
          <span class="big">{revenue ? `${pln(revenue.services_total)} zł` : '—'}</span>
          {revenue && (
            <span class="muted small">
              Booksy {pln(revenue.booksy_services)} · gotówka {pln(revenue.cash_services)} · zeszyt{' '}
              {pln(revenue.notebook_services)}
            </span>
          )}
        </div>
        <div class="stat">
          <span class="lbl">Prowizja (podgląd)</span>
          <span class="big pay">{commission ? `${pln(commission.total_payout)} zł` : '—'}</span>
          {commission && (
            <span class="muted small">
              stawka {Math.round(Number(commission.services_rate) * 100)}% · godziny{' '}
              {pln(commission.hours)} ({pln(commission.hours_pay, 2)} zł)
            </span>
          )}
        </div>
      </div>
      <p class="muted small">
        Podgląd na żywo z bieżących danych — ostateczne rozliczenie zamyka właścicielka.
      </p>

      <h3>Dodaj godziny</h3>
      <div class="addrow">
        <input
          type="date"
          value={hDate}
          disabled={busy}
          onInput={(e) => setHDate((e.target as HTMLInputElement).value)}
        />
        <input
          class="hin"
          type="text"
          inputMode="decimal"
          placeholder="godz. (max 11)"
          value={hVal}
          disabled={busy}
          onInput={(e) => setHVal((e.target as HTMLInputElement).value)}
        />
        <button class="btn" disabled={busy} onClick={addHours}>
          Zapisz
        </button>
      </div>
      {hours.length > 0 && (
        <p class="muted small">
          {hours.map((h) => `${h.work_date}: ${pln(h.hours)} h`).join(' · ')}
        </p>
      )}

      <h3>Dodaj gotówkę</h3>
      <div class="addrow">
        <input
          type="date"
          value={cDate}
          disabled={busy}
          onInput={(e) => setCDate((e.target as HTMLInputElement).value)}
        />
        <input
          class="svc"
          type="text"
          list="me-services"
          placeholder="usługa"
          value={cService}
          disabled={busy}
          onInput={(e) => setCService((e.target as HTMLInputElement).value)}
        />
        <datalist id="me-services">
          {services.map((s) => (
            <option value={s} key={s} />
          ))}
        </datalist>
        <input
          class="hin"
          type="text"
          inputMode="decimal"
          placeholder="kwota zł"
          value={cVal}
          disabled={busy}
          onInput={(e) => setCVal((e.target as HTMLInputElement).value)}
        />
        <button class="btn" disabled={busy} onClick={addCash}>
          Zapisz
        </button>
      </div>
      <p class="muted small">
        Utarg z Booksy dolicza się automatycznie — tu wpisujesz tylko gotówkę poza Booksy.
      </p>

      <h3>Dodaj zeszyt (pakiet / voucher)</h3>
      <div class="addrow">
        <input
          type="date"
          value={nDate}
          disabled={busy}
          onInput={(e) => setNDate((e.target as HTMLInputElement).value)}
        />
        <input
          class="svc"
          type="text"
          list="me-services"
          placeholder="usługa"
          value={nService}
          disabled={busy}
          onInput={(e) => setNService((e.target as HTMLInputElement).value)}
        />
        <input
          class="hin"
          type="text"
          inputMode="decimal"
          placeholder="wartość zł"
          value={nVal}
          disabled={busy}
          onInput={(e) => setNVal((e.target as HTMLInputElement).value)}
        />
        <button class="btn" disabled={busy} onClick={addNotebook}>
          Zapisz
        </button>
      </div>
      <p class="muted small">
        Wizyta opłacona z góry (pakiet/voucher) — Booksy rozlicza ją na 0, prowizja liczy się od
        wartości. Każdy wpis musi mieć wizytę w Booksy tego dnia.
      </p>

      <h3>Mój grafik ({visits.length})</h3>
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>Data</th>
              <th>Klientka</th>
              <th>Usługa</th>
              <th>Kwota</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {visits.map((v) => (
              <tr key={v.id}>
                <td class="nowrap">
                  {new Date(v.starts_at).toLocaleString('pl-PL', {
                    dateStyle: 'short',
                    timeStyle: 'short',
                  })}
                </td>
                <td>{v.client_name}</td>
                <td>{v.service_name}</td>
                <td class="amt">
                  {v.price_pln != null ? `${pln(v.price_pln, 2)} zł` : '—'}
                </td>
                <td>
                  <span class={`badge s-${v.status}`}>{STATUS_PL[v.status] ?? v.status}</span>
                </td>
              </tr>
            ))}
            {visits.length === 0 && !error && (
              <tr>
                <td colSpan={5} class="muted" style="text-align:center;padding:1.5rem">
                  Brak wizyt w tym miesiącu.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <h3>Dyspozycyjność ({month})</h3>
      <div class="addrow">
        <input
          type="date"
          value={aDate}
          disabled={busy}
          onInput={(e) => setADate((e.target as HTMLInputElement).value)}
        />
        <button class="btn" disabled={busy} onClick={addAvailability}>
          Dodaj dzień
        </button>
      </div>
      {avail.length > 0 && (
        <p class="muted small chips">
          {avail.map((a) => (
            <span class="chip" key={a.id}>
              {a.work_date}
              <button class="x" title="Usuń" disabled={busy} onClick={() => delAvailability(a.id)}>
                ×
              </button>
            </span>
          ))}
        </p>
      )}

      <h3>Urlopy / wolne</h3>
      <div class="addrow">
        <input
          type="date"
          value={oStart}
          disabled={busy}
          onInput={(e) => setOStart((e.target as HTMLInputElement).value)}
        />
        <span class="muted">→</span>
        <input
          type="date"
          value={oEnd}
          disabled={busy}
          onInput={(e) => setOEnd((e.target as HTMLInputElement).value)}
        />
        <button class="btn" disabled={busy} onClick={addTimeOff}>
          Zgłoś
        </button>
      </div>
      {off.length > 0 && (
        <ul class="offlist">
          {off.map((o) => (
            <li key={o.id}>
              {o.start_date} → {o.end_date} · {o.kind}
              <span class={`badge ${o.status === 'approved' ? 's-completed' : 's-scheduled'}`}>
                {o.status === 'approved' ? 'zaakceptowany' : 'oczekuje'}
              </span>
              <button class="x" title="Usuń" disabled={busy} onClick={() => delTimeOff(o.id)}>
                ×
              </button>
            </li>
          ))}
        </ul>
      )}

      <h3>Moje dokumenty</h3>
      <ul class="offlist">
        {docs.map((d) => (
          <li key={d.id}>
            <b>{d.doc_type}</b>
            {d.title ? ` · ${d.title}` : ''}
            {d.valid_until ? ` · ważne do ${d.valid_until}` : ''}
          </li>
        ))}
        {docs.length === 0 && (
          <li class="muted small">Brak dokumentów — doda je właścicielka.</li>
        )}
      </ul>
    </div>
  );
}
