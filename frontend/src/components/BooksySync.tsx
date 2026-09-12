// Booksy sync (F5): paste the current session credentials, then pull the visits
// report for a month straight from Booksy — no manual xlsx. The report_key for
// the visits list is 'appointments_list'.
import { useEffect, useState } from 'preact/hooks';
import { getUser, groupsOf, login } from '../lib/auth';
import { apiFetch } from '../lib/api';

interface PullSummary {
  visits_in_file: number;
  clients_created: number;
  visits_created: number;
  visits_updated: number;
}
interface CostSummary {
  year_month: string;
  ledger_created: number;
  salon_days_created: number;
  per_employee: Record<string, string>;
  unmatched_names: string[];
  checksum_ok: boolean;
  checksum_note: string;
  sheet_used: string | null;
  sheets_seen: string[];
}

function thisYm(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function monthRange(): { from: string; till: string } {
  const d = new Date();
  const y = d.getFullYear();
  const m = d.getMonth(); // 0-based
  const first = new Date(y, m, 1);
  const last = new Date(y, m + 1, 0);
  const iso = (x: Date) =>
    `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
  return { from: iso(first), till: iso(last) };
}

export default function BooksySync() {
  const [ready, setReady] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // credentials
  const [businessId, setBusinessId] = useState('221497');
  const [token, setToken] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [fingerprint, setFingerprint] = useState('');

  // pull range
  const init = monthRange();
  const [reportKey] = useState('appointments_list');
  const [from, setFrom] = useState(init.from);
  const [till, setTill] = useState(init.till);
  const [summary, setSummary] = useState<PullSummary | null>(null);

  // costs (zabiegi_koszty) import
  const [costMonth, setCostMonth] = useState(thisYm());
  const [costFile, setCostFile] = useState<File | null>(null);
  const [costSummary, setCostSummary] = useState<CostSummary | null>(null);

  useEffect(() => {
    (async () => {
      const user = await getUser();
      if (user && !user.expired) {
        // Staff must never see admin pages, nor that admin exists — bounce them
        // to their own portal. Anonymous visitors fall through to a neutral login.
        if (!groupsOf(user).includes('admin')) {
          window.location.replace('/panel/pracownik');
          return;
        }
        setIsAdmin(true);
      }
      setReady(true);
    })();
  }, []);

  async function saveCreds() {
    setError(null);
    setOk(null);
    if (!token || !apiKey || !fingerprint) {
      setError('Uzupełnij token, api-key i fingerprint.');
      return;
    }
    setBusy(true);
    try {
      await apiFetch('/imports/booksy/credentials', {
        method: 'PUT',
        body: JSON.stringify({
          business_id: businessId,
          access_token: token,
          api_key: apiKey,
          fingerprint,
        }),
      });
      setOk('Poświadczenia zapisane. Możesz synchronizować.');
      setToken('');
      setApiKey('');
      setFingerprint('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function pull() {
    setError(null);
    setOk(null);
    setSummary(null);
    setBusy(true);
    try {
      const s = await apiFetch<PullSummary>('/imports/booksy/pull', {
        method: 'POST',
        body: JSON.stringify({ report_key: reportKey, date_from: from, date_till: till }),
      });
      setSummary(s);
      setOk('Zsynchronizowano.');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function importCosts() {
    setError(null);
    setOk(null);
    setCostSummary(null);
    if (!costFile) {
      setError('Wybierz plik .xlsx arkusza gotówki.');
      return;
    }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append('year_month', costMonth);
      fd.append('file', costFile);
      const s = await apiFetch<CostSummary>('/imports/costs', { method: 'POST', body: fd });
      setCostSummary(s);
      setOk(`Zaimportowano gotówkę za ${s.year_month}.`);
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
        <h2>Synchronizacja Booksy</h2>
        <p class="muted">Zaloguj się, aby kontynuować.</p>
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
      </div>
      {error && <div class="err">Błąd: {error}</div>}
      {ok && <div class="ok">{ok}</div>}

      <div class="cards">
        <div class="empcard">
          <div class="secthead">1. Poświadczenia Booksy</div>
          <p class="muted small">
            Z sesji Booksy (DevTools → Network → dowolne żądanie do <code>business_api</code> →
            nagłówki). Token wygasa ~co dobę — odśwież tutaj, gdy synchronizacja zwróci „token
            wygasł". Nie trafia do repozytorium.
          </p>
          <div class="frm">
            <label>
              business_id
              <input class="fld" value={businessId} onInput={(e) => setBusinessId((e.target as HTMLInputElement).value)} />
            </label>
            <label>
              x-access-token
              <input class="fld" type="password" value={token} placeholder="wklej token" onInput={(e) => setToken((e.target as HTMLInputElement).value)} />
            </label>
            <label>
              x-api-key
              <input class="fld" value={apiKey} placeholder="wklej api-key" onInput={(e) => setApiKey((e.target as HTMLInputElement).value)} />
            </label>
            <label>
              x-fingerprint
              <input class="fld" value={fingerprint} placeholder="wklej fingerprint" onInput={(e) => setFingerprint((e.target as HTMLInputElement).value)} />
            </label>
            <button class="btn primary" disabled={busy} onClick={saveCreds}>
              Zapisz poświadczenia
            </button>
          </div>
        </div>

        <div class="empcard">
          <div class="secthead">2. Pobierz wizyty</div>
          <p class="muted small">
            Raport <code>appointments_list</code> za wybrany zakres → wizyty i klientki
            aktualizują się w bazie (idempotentnie).
          </p>
          <div class="frm">
            <label>
              od
              <input class="fld" type="date" value={from} onInput={(e) => setFrom((e.target as HTMLInputElement).value)} />
            </label>
            <label>
              do
              <input class="fld" type="date" value={till} onInput={(e) => setTill((e.target as HTMLInputElement).value)} />
            </label>
            <button class="btn primary" disabled={busy} onClick={pull}>
              {busy ? 'Synchronizuję…' : 'Synchronizuj z Booksy'}
            </button>
          </div>
          {summary && (
            <ul class="summary">
              <li>Wizyt w raporcie: <b>{summary.visits_in_file}</b></li>
              <li>Nowych wizyt: <b>{summary.visits_created}</b></li>
              <li>Zaktualizowanych: <b>{summary.visits_updated}</b></li>
              <li>Nowych klientek: <b>{summary.clients_created}</b></li>
            </ul>
          )}
        </div>

        <div class="empcard">
          <div class="secthead">3. Import arkusza gotówki (miesiąc)</div>
          <p class="muted small">
            Plik <code>zabiegi_koszty</code> jako <code>.xlsx</code> (Excel → Zapisz jako). Gotówka
            „nie wbita" per pracownica + kasa fiskalna trafią do wybranego miesiąca. <b>Zastępuje</b>{' '}
            dane gotówkowe tego miesiąca — do backfillu historii. Działa też na starszych miesiącach.
          </p>
          <div class="frm">
            <label>
              miesiąc
              <input class="fld" type="month" value={costMonth} onInput={(e) => setCostMonth((e.target as HTMLInputElement).value)} />
            </label>
            <label>
              plik .xlsx
              <input
                class="fld"
                type="file"
                accept=".xlsx"
                onInput={(e) => setCostFile((e.target as HTMLInputElement).files?.[0] ?? null)}
              />
            </label>
            <button class="btn primary" disabled={busy} onClick={importCosts}>
              {busy ? 'Importuję…' : 'Importuj gotówkę'}
            </button>
          </div>
          {costSummary && (
            <ul class="summary">
              <li>Wpisów gotówki: <b>{costSummary.ledger_created}</b> · dni kasy: <b>{costSummary.salon_days_created}</b></li>
              <li class="muted small">
                zakładka: <b>{costSummary.sheet_used ?? '—'}</b> · w pliku: {costSummary.sheets_seen.join(', ') || '—'}
              </li>
              {Object.entries(costSummary.per_employee).map(([n, s]) => (
                <li key={n}>{n}: <b>{Number(s).toLocaleString('pl-PL')} zł</b></li>
              ))}
              {costSummary.unmatched_names.length > 0 && (
                <li class="warn">Bez aliasu (gotówka pominięta): {costSummary.unmatched_names.join(', ')}</li>
              )}
              <li class={costSummary.checksum_ok ? 'okrow' : 'warn'}>
                {costSummary.checksum_ok ? '✓ ' : '⚠ '}
                {costSummary.checksum_note}
              </li>
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
