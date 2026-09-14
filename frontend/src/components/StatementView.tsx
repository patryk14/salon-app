// Bank statement → costs (admin). Upload an ING .sta (MT940), review the parsed
// debits — assign a category to the ambiguous ones, ignore the non-costs (staff
// salaries, owner draws) — then materialize them into the month's P&L expenses.
import { useEffect, useState } from 'preact/hooks';
import { getUser, groupsOf, login } from '../lib/auth';
import { apiFetch } from '../lib/api';

interface Txn {
  id: number;
  value_date: string;
  amount: string;
  counterparty: string;
  title: string;
  category: string | null;
  name: string;
  bucket: string;
  status: string;
}
interface Cat {
  code: string;
  name: string;
}
interface ImportSummary {
  year_month: string;
  parsed: number;
  added: number;
  duplicates: number;
  needs_review: number;
}

const pln = (v: string) =>
  Number(v).toLocaleString('pl-PL', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const BUCKET: Record<string, string> = {
  staff: 'wynagrodzenie',
  owner_draw: 'wypłata właściciela',
  unknown: 'do przypisania',
};

function thisMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

export default function StatementView() {
  const [ready, setReady] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [ym, setYm] = useState(thisMonth());
  const [txns, setTxns] = useState<Txn[]>([]);
  const [cats, setCats] = useState<Cat[]>([]);
  const [summary, setSummary] = useState<ImportSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
      const [t, c] = await Promise.all([
        apiFetch<Txn[]>(`/statements?month=${ym}`),
        apiFetch<Cat[]>('/expenses/categories'),
      ]);
      setTxns(t);
      setCats(c);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (ready && isAdmin) load();
  }, [ready, isAdmin, ym]);

  async function upload(e: Event) {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    setError(null);
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const s = await apiFetch<ImportSummary>('/statements/import', { method: 'POST', body: fd });
      setSummary(s);
      if (s.year_month) setYm(s.year_month);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
      input.value = '';
    }
  }

  async function patch(id: number, body: Record<string, unknown>) {
    setError(null);
    try {
      await apiFetch(`/statements/${id}`, { method: 'PUT', body: JSON.stringify(body) });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function materialize() {
    setBusy(true);
    setError(null);
    try {
      const m = await apiFetch<{ expenses_created: number; unassigned: number }>(
        `/statements/materialize?month=${ym}`,
        { method: 'POST' },
      );
      if (m.unassigned > 0)
        setError(`Zatwierdzono. Pozostało ${m.unassigned} pozycji bez kategorii do przypisania.`);
      await load();
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
        <h2>Wyciąg → koszty</h2>
        <p class="muted">Zaloguj się, aby kontynuować.</p>
        <button class="btn primary" onClick={() => login()}>
          Zaloguj przez Cognito
        </button>
      </div>
    );
  }

  const pending = txns.filter((t) => t.status === 'pending');
  const ignored = txns.filter((t) => t.status === 'ignored');
  const imported = txns.filter((t) => t.status === 'imported');
  const readyToPost = pending.filter((t) => t.category).length;

  const catSelect = (t: Txn) => (
    <select
      value={t.category ?? ''}
      disabled={t.status === 'imported'}
      onChange={(e) =>
        patch(
          t.id,
          (e.target as HTMLSelectElement).value
            ? { category: (e.target as HTMLSelectElement).value }
            : { clear_category: true },
        )
      }
    >
      <option value="">— wybierz —</option>
      {cats.map((c) => (
        <option value={c.code} key={c.code}>
          {c.name}
        </option>
      ))}
    </select>
  );

  const row = (t: Txn) => (
    <tr key={t.id}>
      <td class="nowrap">{t.value_date}</td>
      <td>
        <div>{t.counterparty || '—'}</div>
        <div class="muted small">{t.title}</div>
      </td>
      <td class="amt">{pln(t.amount)}</td>
      <td>{catSelect(t)}</td>
      <td>
        {t.bucket !== 'operating' && <span class="tag">{BUCKET[t.bucket] ?? t.bucket}</span>}
      </td>
      <td class="del">
        {t.status === 'pending' && (
          <button class="link" onClick={() => patch(t.id, { status: 'ignored' })}>
            ignoruj
          </button>
        )}
        {t.status === 'ignored' && (
          <button class="link" onClick={() => patch(t.id, { status: 'pending' })}>
            przywróć
          </button>
        )}
      </td>
    </tr>
  );

  return (
    <div>
      {error && <div class="err">{error}</div>}

      <div class="bar">
        <label class="fld">
          <span class="lbl">Miesiąc</span>
          <input type="month" value={ym} onChange={(e) => setYm((e.target as HTMLInputElement).value)} />
        </label>
        <label class="btn">
          Wczytaj wyciąg (.sta)
          <input type="file" accept=".sta,.mt940,.txt" hidden disabled={busy} onChange={upload} />
        </label>
        <span class="spacer" />
        <a class="btn" href="/panel/wydatki">
          → P&amp;L
        </a>
      </div>

      {summary && (
        <p class="muted small">
          Wczytano <b>{summary.parsed}</b> obciążeń · nowych <b>{summary.added}</b> · duplikatów{' '}
          <b>{summary.duplicates}</b> · do przypisania <b>{summary.needs_review}</b>.
        </p>
      )}

      <p class="muted small">
        Obciążenia z banku. Przypisz kategorię pozycjom „do przypisania", zignoruj wynagrodzenia
        (koszt pracownic liczymy z rozliczeń) i wypłaty własne. Potem zatwierdź — trafią do kosztów
        miesiąca, a szablonowe koszty stałe zostaną zastąpione realnymi kwotami z wyciągu.
      </p>

      <div class="cat-head">
        <h2>Do rozliczenia ({pending.length})</h2>
        <button class="btn primary" disabled={busy || readyToPost === 0} onClick={materialize}>
          Zatwierdź do kosztów ({readyToPost})
        </button>
      </div>
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>Data</th>
              <th>Kontrahent / tytuł</th>
              <th class="amt">Kwota</th>
              <th>Kategoria</th>
              <th></th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {pending.map(row)}
            {pending.length === 0 && (
              <tr>
                <td colSpan={6} class="muted" style="text-align:center;padding:1.2rem">
                  Brak pozycji do rozliczenia — wczytaj wyciąg.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {ignored.length > 0 && (
        <details class="fold">
          <summary>Zignorowane ({ignored.length}) — wynagrodzenia, wypłaty własne</summary>
          <div class="scroll">
            <table>
              <tbody>{ignored.map(row)}</tbody>
            </table>
          </div>
        </details>
      )}

      {imported.length > 0 && (
        <details class="fold">
          <summary>Rozliczone ({imported.length})</summary>
          <div class="scroll">
            <table>
              <tbody>
                {imported.map((t) => (
                  <tr key={t.id}>
                    <td class="nowrap">{t.value_date}</td>
                    <td>{t.counterparty}</td>
                    <td class="amt">{pln(t.amount)}</td>
                    <td>{t.name}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}
