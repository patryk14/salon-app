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
  const [hDate, setHDate] = useState('');
  const [hVal, setHVal] = useState('');
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
      const [rev, com, vis, hrs] = await Promise.all([
        apiFetch<Revenue>(`/me/revenue?month=${month}`),
        apiFetch<Commission>(`/me/commission?month=${month}`),
        apiFetch<Visit[]>(`/me/visits?month=${month}`),
        apiFetch<Hours[]>(`/me/hours?month=${month}`),
      ]);
      setRevenue(rev);
      setCommission(com);
      setVisits(vis);
      setHours(hrs);
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
    </div>
  );
}
