// Packages (admin) — Booksy-synced, plus manual correction. Mark a treatment
// used by hand when Booksy missed it (optional performer → commission), and
// assign the performer to redemptions Booksy couldn't match. Every manual change
// is stamped with who + when.
import { useEffect, useState } from 'preact/hooks';
import { getUser, groupsOf, login } from '../lib/auth';
import { apiFetch } from '../lib/api';

interface Pkg {
  id: number;
  client_name: string;
  name: string;
  total_value: string;
  total_treatments: number;
  remaining: number;
  used: number;
  value_per_treatment: string;
  valid_until: string | null;
  status: string;
  manual_used: number;
  effective_remaining: number;
}
interface Emp {
  id: number;
  display_name: string;
}
interface Redemption {
  id: number;
  package_id: number | null;
  package_name: string | null;
  client_name: string;
  redemption_date: string;
  value: string;
  employee_id: number | null;
  employee_name: string | null;
  source: string;
  note: string | null;
  created_by: string | null;
  assigned_by: string | null;
  created_at: string;
}

const pln = (v: string) => Number(v).toLocaleString('pl-PL', { maximumFractionDigits: 0 });
const STATUS_PL: Record<string, string> = { active: 'aktywny', used_up: 'wykorzystany', expired: 'wygasły' };
const today = () => new Date().toISOString().slice(0, 10);

export default function PackagesView() {
  const [ready, setReady] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [rows, setRows] = useState<Pkg[]>([]);
  const [emps, setEmps] = useState<Emp[]>([]);
  const [unmatched, setUnmatched] = useState<Redemption[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const [form, setForm] = useState<{ employee_id: string; note: string; date: string }>({
    employee_id: '',
    note: '',
    date: today(),
  });

  useEffect(() => {
    (async () => {
      const user = await getUser();
      if (user && !user.expired) {
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
      const [p, e, u] = await Promise.all([
        apiFetch<Pkg[]>('/packages'),
        apiFetch<Emp[]>('/employees'),
        apiFetch<Redemption[]>('/packages/redemptions/unmatched'),
      ]);
      setRows(p);
      setEmps(e);
      setUnmatched(u);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    if (ready && isAdmin) load();
  }, [ready, isAdmin]);

  async function call(path: string, init: RequestInit) {
    setError(null);
    setBusy(true);
    try {
      await apiFetch(path, init);
      await load();
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function redeem(pkgId: number) {
    const ok = await call(`/packages/${pkgId}/redeem`, {
      method: 'POST',
      body: JSON.stringify({
        employee_id: form.employee_id ? Number(form.employee_id) : null,
        redemption_date: form.date || today(),
        note: form.note || null,
      }),
    });
    if (ok) {
      setForm({ employee_id: '', note: '', date: today() });
      setOpen(null);
    }
  }

  const assign = (redId: number, employee_id: string) =>
    call(`/packages/redemptions/${redId}`, {
      method: 'PUT',
      body: JSON.stringify({ employee_id: Number(employee_id) }),
    });

  if (!ready) return <p class="muted">Ładowanie…</p>;
  if (!isAdmin) {
    return (
      <div class="gate">
        <h2>Pakiety</h2>
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
      <p class="muted small">
        Synchronizowane z Booksy. Rozwiń pakiet, aby ręcznie odznaczyć zabieg (gdy Booksy nie
        zaciągnął) — wskaż wykonawczynię, by naliczyć prowizję. Każda ręczna zmiana zapisuje kto i
        kiedy.
      </p>

      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>Klientka</th>
              <th>Pakiet</th>
              <th class="amt">Wart./zabieg</th>
              <th class="amt">Zostało</th>
              <th>Ważny do</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <>
                <tr key={p.id} class="clickable" onClick={() => setOpen(open === p.id ? null : p.id)}>
                  <td>{p.client_name}</td>
                  <td class="muted small">{p.name}</td>
                  <td class="amt">{pln(p.value_per_treatment)} zł</td>
                  <td class="amt">
                    <b>{p.effective_remaining}</b> / {p.total_treatments}
                    {p.manual_used > 0 && <span class="tag" title="ręcznie odznaczone"> +{p.manual_used}</span>}
                  </td>
                  <td class="nowrap">{p.valid_until ?? '—'}</td>
                  <td>
                    <span class={`badge s-${p.status}`}>{STATUS_PL[p.status] ?? p.status}</span>
                  </td>
                  <td class="nowrap">{open === p.id ? '▾' : '▸'}</td>
                </tr>
                {open === p.id && (
                  <tr class="detail">
                    <td colSpan={7}>
                      <div class="redeem">
                        <span class="lbl">Odznacz zabieg:</span>
                        <select
                          value={form.employee_id}
                          onChange={(e) => setForm({ ...form, employee_id: (e.target as HTMLSelectElement).value })}
                        >
                          <option value="">— bez prowizji —</option>
                          {emps.map((e) => (
                            <option value={e.id} key={e.id}>
                              {e.display_name}
                            </option>
                          ))}
                        </select>
                        <input
                          type="date"
                          value={form.date}
                          onInput={(e) => setForm({ ...form, date: (e.target as HTMLInputElement).value })}
                        />
                        <input
                          placeholder="notatka (np. late cancel)"
                          value={form.note}
                          onInput={(e) => setForm({ ...form, note: (e.target as HTMLInputElement).value })}
                        />
                        <button class="btn sm primary" disabled={busy} onClick={() => redeem(p.id)}>
                          Odznacz
                        </button>
                      </div>
                      <p class="muted small">
                        Wykonawczyni → prowizja {pln(p.value_per_treatment)} zł doliczona w miesiącu
                        odznaczenia. Bez wykonawczyni: tylko korekta licznika.
                      </p>
                    </td>
                  </tr>
                )}
              </>
            ))}
            {rows.length === 0 && !error && (
              <tr>
                <td colSpan={7} class="muted" style="text-align:center;padding:1.5rem">
                  Brak pakietów — zsynchronizuj z Booksy.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <h2 class="section">Realizacje do przypisania ({unmatched.length})</h2>
      <p class="muted small">
        Realizacje z Booksy, którym brakuje wykonawczyni lub powiązanego pakietu — przypisz ręcznie
        (zapisze kto i kiedy).
      </p>
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>Data</th>
              <th>Klientka</th>
              <th>Pakiet</th>
              <th class="amt">Wartość</th>
              <th>Wykonawczyni</th>
            </tr>
          </thead>
          <tbody>
            {unmatched.map((r) => (
              <tr key={r.id}>
                <td class="nowrap">{r.redemption_date}</td>
                <td>{r.client_name}</td>
                <td class="muted small">{r.package_name ?? <span class="tag">brak pakietu</span>}</td>
                <td class="amt">{pln(r.value)} zł</td>
                <td>
                  <select
                    value={r.employee_id ?? ''}
                    disabled={busy}
                    onChange={(e) => assign(r.id, (e.target as HTMLSelectElement).value)}
                  >
                    <option value="">— wskaż —</option>
                    {emps.map((e) => (
                      <option value={e.id} key={e.id}>
                        {e.display_name}
                      </option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
            {unmatched.length === 0 && (
              <tr>
                <td colSpan={5} class="muted" style="text-align:center;padding:1.2rem">
                  Wszystko przypisane. 🎉
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
