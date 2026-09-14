// Vouchers (admin) — value-based gift cards tracked by hand. Add, draw down the
// balance (partial redemptions with a who+when audit trail), and seed the list
// best-effort from VOUCHERY.docx. Booksy doesn't know vouchers, so it's all here.
import { useEffect, useState } from 'preact/hooks';
import { getUser, groupsOf, login } from '../lib/auth';
import { apiFetch } from '../lib/api';

interface Redemption {
  id: number;
  amount: string;
  redeemed_on: string;
  note: string | null;
  created_by: string | null;
  created_at: string;
}
interface Voucher {
  id: number;
  client_name: string;
  description: string;
  total_value: string;
  remaining_value: string;
  purchased_on: string | null;
  valid_until: string | null;
  status: string;
  note: string | null;
  source: string;
  redemptions: Redemption[];
}

const pln = (v: string) =>
  Number(v).toLocaleString('pl-PL', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
const STATUS_PL: Record<string, string> = { active: 'aktywny', used: 'wykorzystany', expired: 'wygasły' };
const today = () => new Date().toISOString().slice(0, 10);
const when = (iso: string) => new Date(iso).toLocaleDateString('pl-PL');

export default function VouchersView() {
  const [ready, setReady] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [rows, setRows] = useState<Voucher[]>([]);
  const [filter, setFilter] = useState('active');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const [redeem, setRedeem] = useState<{ amount: string; note: string }>({ amount: '', note: '' });
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ client_name: '', description: '', total_value: '', valid_until: '' });

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
      const q = filter === 'all' ? '' : `?status=${filter}`;
      setRows(await apiFetch<Voucher[]>(`/vouchers${q}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (ready && isAdmin) load();
  }, [ready, isAdmin, filter]);

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

  async function addVoucher() {
    if (!form.client_name.trim() || !form.total_value) return;
    const ok = await call('/vouchers', {
      method: 'POST',
      body: JSON.stringify({
        client_name: form.client_name,
        description: form.description || `${form.total_value} zł`,
        total_value: form.total_value,
        valid_until: form.valid_until || null,
      }),
    });
    if (ok) {
      setForm({ client_name: '', description: '', total_value: '', valid_until: '' });
      setAdding(false);
    }
  }

  async function doRedeem(id: number) {
    if (!redeem.amount) return;
    const ok = await call(`/vouchers/${id}/redeem`, {
      method: 'POST',
      body: JSON.stringify({ amount: redeem.amount, redeemed_on: today(), note: redeem.note || null }),
    });
    if (ok) setRedeem({ amount: '', note: '' });
  }

  async function upload(e: Event) {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    setBusy(true);
    setError(null);
    try {
      const s = await apiFetch<{ imported: number; skipped_inactive: number; skipped_existing: number }>(
        '/vouchers/import',
        { method: 'POST', body: fd },
      );
      setError(
        `Zaimportowano ${s.imported} aktywnych (pominięto ${s.skipped_inactive} nieaktywnych, ${s.skipped_existing} istniejących). Ustaw „zostało" dla częściowo wykorzystanych.`,
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
      input.value = '';
    }
  }

  if (!ready) return <p class="muted">Ładowanie…</p>;
  if (!isAdmin) {
    return (
      <div class="gate">
        <h2>Vouchery</h2>
        <p class="muted">Zaloguj się, aby kontynuować.</p>
        <button class="btn primary" onClick={() => login()}>
          Zaloguj przez Cognito
        </button>
      </div>
    );
  }

  return (
    <div>
      {error && <div class="err">{error}</div>}

      <div class="bar">
        <label class="fld">
          <span class="lbl">Pokaż</span>
          <select value={filter} onChange={(e) => setFilter((e.target as HTMLSelectElement).value)}>
            <option value="active">aktywne</option>
            <option value="used">wykorzystane</option>
            <option value="expired">wygasłe</option>
            <option value="all">wszystkie</option>
          </select>
        </label>
        <button class="btn" onClick={() => setAdding((a) => !a)}>
          + Dodaj voucher
        </button>
        <label class="btn">
          Wczytaj z docx
          <input type="file" accept=".docx" hidden disabled={busy} onChange={upload} />
        </label>
      </div>

      {adding && (
        <div class="addform">
          <input
            placeholder="Klientka"
            value={form.client_name}
            onInput={(e) => setForm({ ...form, client_name: (e.target as HTMLInputElement).value })}
          />
          <input
            placeholder="Opis (np. Masaż Kobido)"
            value={form.description}
            onInput={(e) => setForm({ ...form, description: (e.target as HTMLInputElement).value })}
          />
          <input
            type="number"
            step="0.01"
            placeholder="Kwota zł"
            value={form.total_value}
            onInput={(e) => setForm({ ...form, total_value: (e.target as HTMLInputElement).value })}
          />
          <input
            type="date"
            title="Ważny do"
            value={form.valid_until}
            onInput={(e) => setForm({ ...form, valid_until: (e.target as HTMLInputElement).value })}
          />
          <button class="btn primary" disabled={busy} onClick={addVoucher}>
            Zapisz
          </button>
        </div>
      )}

      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>Klientka</th>
              <th>Opis</th>
              <th>Ważny do</th>
              <th class="amt">Zostało / total</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((v) => (
              <>
                <tr key={v.id} class="clickable" onClick={() => setOpen(open === v.id ? null : v.id)}>
                  <td>{v.client_name}</td>
                  <td class="muted small">{v.description}</td>
                  <td class="nowrap">{v.valid_until ?? '—'}</td>
                  <td class="amt">
                    <b>{pln(v.remaining_value)}</b> / {pln(v.total_value)} zł
                  </td>
                  <td>
                    <span class={`badge s-${v.status}`}>{STATUS_PL[v.status] ?? v.status}</span>
                  </td>
                  <td class="nowrap">{open === v.id ? '▾' : '▸'}</td>
                </tr>
                {open === v.id && (
                  <tr class="detail">
                    <td colSpan={6}>
                      {Number(v.remaining_value) > 0 && (
                        <div class="redeem">
                          <span class="lbl">Odznacz wykorzystanie:</span>
                          <input
                            type="number"
                            step="0.01"
                            placeholder="kwota zł"
                            value={redeem.amount}
                            onInput={(e) => setRedeem({ ...redeem, amount: (e.target as HTMLInputElement).value })}
                          />
                          <input
                            placeholder="notatka (opcjonalnie)"
                            value={redeem.note}
                            onInput={(e) => setRedeem({ ...redeem, note: (e.target as HTMLInputElement).value })}
                          />
                          <button class="btn sm primary" disabled={busy} onClick={() => doRedeem(v.id)}>
                            Odznacz
                          </button>
                        </div>
                      )}
                      {v.redemptions.length > 0 ? (
                        <ul class="hist">
                          {v.redemptions.map((r) => (
                            <li key={r.id}>
                              <b>{pln(r.amount)} zł</b> · {r.redeemed_on}
                              {r.note ? ` · ${r.note}` : ''}
                              <span class="muted small">
                                {' '}
                                — {r.created_by ?? '?'}, {when(r.created_at)}
                              </span>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p class="muted small">Brak realizacji.</p>
                      )}
                      <button
                        class="link del"
                        onClick={() => {
                          if (confirm(`Usunąć voucher ${v.client_name}?`))
                            call(`/vouchers/${v.id}`, { method: 'DELETE' });
                        }}
                      >
                        usuń voucher
                      </button>
                    </td>
                  </tr>
                )}
              </>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={6} class="muted" style="text-align:center;padding:1.4rem">
                  Brak voucherów. Dodaj ręcznie lub wczytaj z docx.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
