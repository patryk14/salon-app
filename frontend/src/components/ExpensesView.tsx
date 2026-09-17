// Monthly P&L (admin) — the cost side of the salon, mirroring the owner's sheet.
// Revenue (kasa) and staff cost (settlement payouts) are DERIVED and shown with
// their source; only operating costs are entered here, grouped into her
// categories. Closing a month freezes the derived inputs and locks the costs.
import type { ComponentChildren } from 'preact';
import { useEffect, useState } from 'preact/hooks';
import { getUser, groupsOf, login } from '../lib/auth';
import { apiFetch } from '../lib/api';

interface Line {
  id: number;
  category_code: string;
  name: string;
  amount_pln: string;
  source: string;
  note: string | null;
}
interface Category {
  code: string;
  name: string;
  total: string;
  lines: Line[];
}
interface Pnl {
  year_month: string;
  status: string;
  revenue: string;
  revenue_source: string;
  categories: Category[];
  operating_total: string;
  staff_cost: string;
  staff_cost_source: string;
  costs_total: string;
  profit: string;
  note: string | null;
  closed_at: string | null;
}

const pln = (v: string) =>
  Number(v).toLocaleString('pl-PL', { minimumFractionDigits: 0, maximumFractionDigits: 2 });

const REV_SRC: Record<string, string> = {
  computed: 'z kasy (fiskalny + niewbita)',
  override: 'ręcznie',
  snapshot: 'zamrożone',
};
const STAFF_SRC: Record<string, string> = {
  settlement: 'z rozliczeń (godziny + prowizja)',
  override: 'ręcznie',
  snapshot: 'zamrożone',
  none: 'brak rozliczenia w tym miesiącu',
};

function thisMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

interface StaffRow {
  employee_id: number;
  name: string;
  pay_type: string;
  hours: string;
  revenue: string;
  base_cost: string;
  commission: string;
  total_cost: string;
  breakeven_revenue: string;
  over_under: string;
  needs_base: boolean;
}
interface StaffCost {
  year_month: string;
  rows: StaffRow[];
  total_cost: string;
}

export default function ExpensesView() {
  const [ready, setReady] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [ym, setYm] = useState(thisMonth());
  const [pnl, setPnl] = useState<Pnl | null>(null);
  const [staff, setStaff] = useState<StaffCost | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<Record<string, { name: string; amount: string }>>({});

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

  async function call(path: string, init?: RequestInit) {
    setError(null);
    setBusy(true);
    try {
      setPnl(await apiFetch<Pnl>(path, init));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const load = () => call(`/pnl/${ym}`);

  async function loadStaff() {
    try {
      setStaff(await apiFetch<StaffCost>(`/pnl/${ym}/staff`));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function setSalary(id: number, value: string) {
    setBusy(true);
    try {
      await apiFetch(`/employees/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ monthly_base_pln: value || '0' }),
      });
      await loadStaff();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (ready && isAdmin) {
      load();
      loadStaff();
    }
  }, [ready, isAdmin, ym]);

  const closed = pnl?.status === 'closed';

  function addLine(code: string) {
    const d = draft[code];
    if (!d?.name?.trim()) return;
    call('/expenses', {
      method: 'POST',
      body: JSON.stringify({
        year_month: ym,
        category_code: code,
        name: d.name.trim(),
        amount_pln: d.amount || '0',
      }),
    });
    setDraft({ ...draft, [code]: { name: '', amount: '' } });
  }

  function saveLine(line: Line, field: 'name' | 'amount_pln', value: string) {
    if (value === (field === 'amount_pln' ? line.amount_pln : line.name)) return;
    call(`/expenses/${line.id}`, {
      method: 'PUT',
      body: JSON.stringify({ [field]: field === 'amount_pln' ? value || '0' : value }),
    });
  }

  const deleteLine = (id: number) => call(`/expenses/${id}`, { method: 'DELETE' });

  function override(body: Record<string, unknown>) {
    call(`/pnl/${ym}`, { method: 'PUT', body: JSON.stringify(body) });
  }

  if (!ready) return <p class="muted">Ładowanie…</p>;
  if (!isAdmin) {
    return (
      <div class="gate">
        <h2>Wydatki i zysk</h2>
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

      <div class="bar">
        <label class="fld">
          <span class="lbl">Miesiąc</span>
          <input
            type="month"
            value={ym}
            onChange={(e) => setYm((e.target as HTMLInputElement).value)}
          />
        </label>
        {pnl && (
          <span class={`badge ${closed ? 's-expired' : 's-active'}`}>
            {closed ? 'zamknięty' : 'roboczy'}
          </span>
        )}
        <span class="spacer" />
        {pnl &&
          (closed ? (
            <button class="btn" disabled={busy} onClick={() => call(`/pnl/${ym}/reopen`, { method: 'POST' })}>
              Otwórz ponownie
            </button>
          ) : (
            <button
              class="btn primary"
              disabled={busy}
              onClick={() => {
                if (confirm(`Zamknąć ${ym}? Przychód i koszt pracownic zostaną zamrożone.`))
                  call(`/pnl/${ym}/close`, { method: 'POST' });
              }}
            >
              Zamknij miesiąc
            </button>
          ))}
      </div>

      {pnl && (
        <>
          {/* Summary waterfall — the owner's bottom-of-sheet block. */}
          <div class="pl">
            <Row label="Utarg (kasa fiskalna + gotówka niewbita)" value={pnl.revenue} strong>
              <Derived
                source={REV_SRC[pnl.revenue_source]}
                editable={!closed}
                onOverride={(v) =>
                  v === null
                    ? override({ clear_revenue_override: true })
                    : override({ revenue_override: v })
                }
                overridden={pnl.revenue_source === 'override'}
              />
            </Row>
            <div class="rule" />
            <Row label="Koszty łączne (operacyjne)" value={pnl.operating_total} />
            <Row label="Koszt pracownic" value={pnl.staff_cost}>
              <Derived
                source={STAFF_SRC[pnl.staff_cost_source]}
                editable={!closed}
                onOverride={(v) =>
                  v === null
                    ? override({ clear_staff_cost_override: true })
                    : override({ staff_cost_override: v })
                }
                overridden={pnl.staff_cost_source === 'override'}
              />
            </Row>
            <div class="rule" />
            <Row label="Podsumowanie kosztów" value={pnl.costs_total} strong />
            <Row label="Zarobek" value={pnl.profit} strong accent={Number(pnl.profit) >= 0} />
          </div>

          {staff && staff.rows.length > 0 && (
            <section class="cat">
              <div class="cat-head">
                <h2>Koszt pracownic — break-even</h2>
                <span class="muted small">od jakiego utargu salon zarabia na pracownicy</span>
              </div>
              <div class="scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Pracownica</th>
                      <th class="amt">Utarg</th>
                      <th class="amt">Baza</th>
                      <th class="amt">Prowizja</th>
                      <th class="amt">Koszt</th>
                      <th class="amt">Break-even</th>
                      <th class="amt">Bilans</th>
                    </tr>
                  </thead>
                  <tbody>
                    {staff.rows.map((r) => (
                      <tr key={r.employee_id}>
                        <td>
                          {r.name}
                          {r.pay_type === 'uop_plus_extra' && <span class="tag"> UoP</span>}
                        </td>
                        <td class="amt">{pln(r.revenue)}</td>
                        <td class="amt">
                          {r.needs_base ? (
                            <input
                              class="cell num"
                              type="number"
                              step="1"
                              placeholder="pensja"
                              style="width:6rem"
                              onBlur={(e) => {
                                const v = (e.target as HTMLInputElement).value;
                                if (v) setSalary(r.employee_id, v);
                              }}
                            />
                          ) : (
                            pln(r.base_cost)
                          )}
                        </td>
                        <td class="amt">{pln(r.commission)}</td>
                        <td class="amt">{pln(r.total_cost)}</td>
                        <td class="amt">
                          <b>{pln(r.breakeven_revenue)}</b> zł
                        </td>
                        <td class="amt">
                          <span class={Number(r.over_under) >= 0 ? 'pos' : 'neg'}>
                            {Number(r.over_under) >= 0 ? '+' : ''}
                            {pln(r.over_under)}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p class="muted small">
                Baza = godziny×31,40 (lub stała pensja UoP). Break-even = utarg, przy którym utarg
                pokrywa koszt (baza + prowizja). Bilans = utarg − koszt (na plusie = salon zarabia).
              </p>
            </section>
          )}

          <p class="muted small">
            Koszty stałe podpowiadają się z szablonów przy pierwszym otwarciu miesiąca — poprawiaj
            kwoty wprost w tabeli. Rzeczy płacone co kilka miesięcy dodaj ręcznie w miesiącu zapłaty.
          </p>

          {/* Operating cost categories */}
          {pnl.categories.map((cat) => (
            <section class="cat" key={cat.code}>
              <div class="cat-head">
                <h2>{cat.name}</h2>
                <span class="cat-total">{pln(cat.total)} zł</span>
              </div>
              <div class="scroll">
                <table>
                  <tbody>
                    {cat.lines.map((line) => (
                      <tr key={line.id}>
                        <td>
                          <input
                            class="cell"
                            defaultValue={line.name}
                            disabled={closed}
                            onBlur={(e) => saveLine(line, 'name', (e.target as HTMLInputElement).value)}
                          />
                        </td>
                        <td class="amt">
                          <input
                            class="cell num"
                            type="number"
                            step="0.01"
                            defaultValue={line.amount_pln}
                            disabled={closed}
                            onBlur={(e) =>
                              saveLine(line, 'amount_pln', (e.target as HTMLInputElement).value)
                            }
                          />
                        </td>
                        <td class="src">
                          {line.source === 'recurring' && <span class="tag">stałe</span>}
                        </td>
                        <td class="del">
                          {!closed && (
                            <button class="x" title="Usuń" onClick={() => deleteLine(line.id)}>
                              ×
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                    {!closed && (
                      <tr class="add">
                        <td>
                          <input
                            class="cell"
                            placeholder="Nowa pozycja…"
                            value={draft[cat.code]?.name ?? ''}
                            onInput={(e) =>
                              setDraft({
                                ...draft,
                                [cat.code]: {
                                  name: (e.target as HTMLInputElement).value,
                                  amount: draft[cat.code]?.amount ?? '',
                                },
                              })
                            }
                          />
                        </td>
                        <td class="amt">
                          <input
                            class="cell num"
                            type="number"
                            step="0.01"
                            placeholder="0"
                            value={draft[cat.code]?.amount ?? ''}
                            onInput={(e) =>
                              setDraft({
                                ...draft,
                                [cat.code]: {
                                  name: draft[cat.code]?.name ?? '',
                                  amount: (e.target as HTMLInputElement).value,
                                },
                              })
                            }
                            onKeyDown={(e) => e.key === 'Enter' && addLine(cat.code)}
                          />
                        </td>
                        <td colSpan={2}>
                          <button class="btn sm" disabled={busy} onClick={() => addLine(cat.code)}>
                            Dodaj
                          </button>
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
        </>
      )}
    </div>
  );
}

function Row(props: {
  label: string;
  value: string;
  strong?: boolean;
  accent?: boolean;
  children?: ComponentChildren;
}) {
  return (
    <div class={`pl-row${props.strong ? ' strong' : ''}`}>
      <span class="pl-label">
        {props.label}
        {props.children}
      </span>
      <span class={`pl-val${props.accent === false ? ' neg' : props.accent ? ' pos' : ''}`}>
        {pln(props.value)} zł
      </span>
    </div>
  );
}

function Derived(props: {
  source: string;
  editable: boolean;
  overridden: boolean;
  onOverride: (v: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [val, setVal] = useState('');
  return (
    <span class="derived">
      <span class="muted small"> · {props.source}</span>
      {props.editable && !open && (
        <button class="link" onClick={() => setOpen(true)}>
          korekta
        </button>
      )}
      {props.overridden && props.editable && (
        <button class="link" onClick={() => props.onOverride(null)}>
          wróć do wyliczonego
        </button>
      )}
      {open && (
        <span class="ov">
          <input
            class="cell num"
            type="number"
            step="0.01"
            value={val}
            onInput={(e) => setVal((e.target as HTMLInputElement).value)}
          />
          <button
            class="btn sm"
            onClick={() => {
              props.onOverride(val || '0');
              setOpen(false);
            }}
          >
            Zapisz
          </button>
          <button class="link" onClick={() => setOpen(false)}>
            anuluj
          </button>
        </span>
      )}
    </span>
  );
}
