// The admin settlement panel — the browser half of F2/F3. It renders what the
// API returns and sends edits back; the API computes every payout (this never
// does the math), so the numbers here are always the backend's truth.
import { useEffect, useState } from 'preact/hooks';
import { getUser, groupsOf, login, logout } from '../lib/auth';
import { ApiError, apiFetch } from '../lib/api';

interface Employee {
  id: number;
  display_name: string;
  fte_factor: string;
  pay_type: string;
  is_active: boolean;
}
interface Line {
  employee_id: number;
  booksy_services: string;
  booksy_sales: string;
  notebook_services: string;
  cash_services: string;
  hours: string;
  services_base: string;
  services_rate: string;
  services_commission: string;
  sales_commission: string;
  hours_pay: string;
  total_payout: string;
}
interface Period {
  year_month: string;
  status: string;
  lines: Line[];
}
interface Readiness {
  ok: boolean;
  warnings: { employee: string; kind: string; message: string }[];
}

const INPUT_FIELDS = [
  ['booksy_services', 'Booksy usł.'],
  ['booksy_sales', 'Sprzedaż'],
  ['notebook_services', 'Zeszyt'],
  ['cash_services', 'Gotówka'],
  ['hours', 'Godziny'],
] as const;

const pln = (v: string, dec = 0) =>
  Number(v).toLocaleString('pl-PL', { minimumFractionDigits: dec, maximumFractionDigits: dec });

function thisMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

export default function SettlementPanel() {
  const [ready, setReady] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [ym, setYm] = useState(thisMonth());
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [period, setPeriod] = useState<Period | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      const user = await getUser();
      if (user && !user.expired) setIsAdmin(groupsOf(user).includes('admin'));
      setReady(true);
    })();
  }, []);

  async function loadData() {
    setError(null);
    try {
      // Both hit Aurora; fire them together so the ~15 s cold-start (min-0-ACU
      // resume) is paid once, not twice.
      const [emps, p] = await Promise.all([
        apiFetch<Employee[]>('/employees'),
        apiFetch<Period>(`/settlement/periods/${ym}`).catch((e) => {
          if (e instanceof ApiError && e.status === 404) return null;
          throw e;
        }),
      ]);
      setEmployees(emps.filter((e) => e.is_active));
      setPeriod(p);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (ready && isAdmin) loadData();
  }, [ready, isAdmin, ym]);

  const lineOf = (empId: number): Line | undefined =>
    period?.lines.find((l) => l.employee_id === empId);

  async function createPeriod() {
    setBusy(true);
    try {
      await apiFetch('/settlement/periods', {
        method: 'POST',
        body: JSON.stringify({ year_month: ym }),
      });
      await loadData();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveLine(empId: number, field: string, value: string) {
    const existing = lineOf(empId);
    const payload: Record<string, string> = {
      booksy_services: existing?.booksy_services ?? '0',
      booksy_sales: existing?.booksy_sales ?? '0',
      notebook_services: existing?.notebook_services ?? '0',
      cash_services: existing?.cash_services ?? '0',
      hours: existing?.hours ?? '0',
      [field]: value === '' ? '0' : value,
    };
    try {
      const updated = await apiFetch<Line>(`/settlement/periods/${ym}/lines/${empId}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      setPeriod((p) =>
        p
          ? {
              ...p,
              lines: [...p.lines.filter((l) => l.employee_id !== empId), updated],
            }
          : p,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function derive(empId: number) {
    try {
      const updated = await apiFetch<Line>(`/settlement/periods/${ym}/lines/${empId}/derive`, {
        method: 'POST',
      });
      setPeriod((p) =>
        p ? { ...p, lines: [...p.lines.filter((l) => l.employee_id !== empId), updated] } : p,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function deriveAll() {
    setBusy(true);
    setError(null);
    try {
      const p = await apiFetch<Period>(`/settlement/periods/${ym}/derive-all`, { method: 'POST' });
      setPeriod(p);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function closePeriod() {
    setBusy(true);
    setError(null);
    try {
      // Safeguard: surface completeness/anomaly warnings before the (final) close.
      const rd = await apiFetch<Readiness>(`/settlement/periods/${ym}/readiness`);
      if (rd.warnings.length > 0) {
        const list = rd.warnings.map((w) => `• ${w.employee}: ${w.message}`).join('\n');
        const proceed = window.confirm(
          `Znaleziono ${rd.warnings.length} ostrzeżeń:\n\n${list}\n\nZamknąć okres mimo to? (zamknięcia nie da się cofnąć)`,
        );
        if (!proceed) {
          setBusy(false);
          return;
        }
      }
      const p = await apiFetch<Period>(`/settlement/periods/${ym}/close`, { method: 'POST' });
      setPeriod(p);
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
        <h2>Panel administratora</h2>
        <p class="muted">Zaloguj się kontem właścicielki, aby zobaczyć rozliczenia.</p>
        <button class="btn primary" onClick={() => login()}>
          Zaloguj przez Cognito
        </button>
        <p class="muted small">
          Jeśli jesteś zalogowana, ale to widzisz — konto nie ma roli <code>admin</code>.
        </p>
      </div>
    );
  }

  const closed = period?.status === 'closed';
  const canEdit = Boolean(period) && !closed;
  const total = (period?.lines ?? []).reduce((s, l) => s + Number(l.total_payout), 0);

  return (
    <div>
      <div class="bar">
        <label>
          Okres:{' '}
          <input class="month" type="month" value={ym} onInput={(e) => setYm((e.target as HTMLInputElement).value)} />
        </label>
        {period && (
          <span class={`badge ${closed ? 'closed' : 'draft'}`}>{closed ? 'Zamknięty' : 'Szkic'}</span>
        )}
        <a class="btn" href="/panel/dzien">
          Raport dzienny
        </a>
        <a class="btn" href="/panel/wizyty">
          Wizyty
        </a>
        <a class="btn" href="/panel/booksy">
          Synchronizacja Booksy
        </a>
        <span class="spacer" />
        {period && !closed && (
          <button class="btn" disabled={busy} onClick={deriveAll} title="Złóż miesiąc z godzin, gotówki i wizyt Booksy">
            Zassij wszystko z ewidencji
          </button>
        )}
        {period && !closed && (
          <button class="btn primary" disabled={busy} onClick={closePeriod}>
            Zamknij okres
          </button>
        )}
        <button class="btn" onClick={() => logout()}>
          Wyloguj
        </button>
      </div>

      {error && <div class="err">Błąd: {error}</div>}

      {employees.length === 0 && !error && (
        <p class="muted">Budzimy serwer i wczytujemy dane… (do ~15 s po dłuższej przerwie)</p>
      )}

      {!period && employees.length > 0 && (
        <div class="banner">
          <span>
            Okres <b>{ym}</b> nie został jeszcze otwarty. Utwórz go, aby wprowadzać liczby i liczyć
            wypłaty.
          </span>
          <button class="btn primary" disabled={busy} onClick={createPeriod}>
            Utwórz okres {ym}
          </button>
        </div>
      )}

      {employees.length > 0 && (
        <div class="scroll">
          <table>
            <thead>
              <tr>
                <th>Pracownica</th>
                {INPUT_FIELDS.map(([, label]) => (
                  <th>{label}</th>
                ))}
                <th>Baza</th>
                <th>Stawka</th>
                <th>Prow.</th>
                <th>Godz.</th>
                <th>Wypłata</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {employees.map((emp) => {
                const line = lineOf(emp.id);
                return (
                  <tr key={emp.id}>
                    <td class="name">
                      {emp.display_name}
                      <span class="fte">{Number(emp.fte_factor) === 1 ? 'pełny' : emp.fte_factor}</span>
                    </td>
                    {INPUT_FIELDS.map(([field]) => (
                      <td>
                        <input
                          class="cell"
                          type="text"
                          inputMode="decimal"
                          disabled={!canEdit}
                          value={line ? (line as unknown as Record<string, string>)[field] : ''}
                          placeholder="0"
                          onBlur={(e) => saveLine(emp.id, field, (e.target as HTMLInputElement).value)}
                        />
                      </td>
                    ))}
                    <td class="out">{line ? pln(line.services_base) : '—'}</td>
                    <td class="rate">{line ? `${Math.round(Number(line.services_rate) * 100)}%` : '—'}</td>
                    <td class="out">{line ? pln(line.services_commission, 2) : '—'}</td>
                    <td class="out">{line && Number(line.hours_pay) ? pln(line.hours_pay, 2) : '—'}</td>
                    <td class="payout">{line ? `${pln(line.total_payout)} zł` : '—'}</td>
                    <td>
                      {canEdit && (
                        <button class="mini" title="Zassij godziny i gotówkę z ewidencji" onClick={() => derive(emp.id)}>
                          zassij
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr>
                <td>Razem</td>
                <td colSpan={9}></td>
                <td class="payout">{pln(String(total))} zł</td>
                <td></td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  );
}
