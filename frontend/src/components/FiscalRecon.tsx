// Fiscal reconciliation for one day: Booksy's till vs the fiscal printer's daily
// report. A positive gap = something was settled in Booksy but never rung up; the
// API then names the matching transaction(s) — to admins only.
import { useEffect, useState } from 'preact/hooks';
import { apiFetch } from '../lib/api';

interface Txn {
  doc: string | null;
  client: string | null;
  performer: string | null;
  cashier: string | null;
  method: string | null;
  amount: string;
}
interface Recon {
  status: 'no_report' | 'ok' | 'gap' | 'explained';
  booksy_till: string;
  fiscal_printer_total: string | null;
  gap: string | null;
  note: string | null;
  synced: boolean;
  candidates: Txn[][];
  transactions: Txn[];
}

const pln = (v: string | number) =>
  Number(v).toLocaleString('pl-PL', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function FiscalRecon(props: { day: string; refresh: number; isAdmin: boolean; onChange: () => void }) {
  const { day, refresh, isAdmin, onChange } = props;
  const [rec, setRec] = useState<Recon | null>(null);
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<Recon>(`/salon-days/${day}/reconciliation`)
      .then((r) => {
        setRec(r);
        setNote(r.note ?? '');
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [day, refresh]);

  if (error) return <div class="err">{error}</div>;
  if (!rec) return null;

  async function explain(value: boolean) {
    if (!rec) return;
    if (value && !note.trim()) {
      setError('Wpisz krótkie wyjaśnienie różnicy.');
      return;
    }
    try {
      // booksy_cash / fiscal_register come from the Booksy sync — resend them as they are
      const cur = await apiFetch<{ booksy_cash: string; fiscal_register: string }>(`/salon-days/${day}`);
      await apiFetch(`/salon-days/${day}`, {
        method: 'PUT',
        body: JSON.stringify({ ...cur, note: note.trim() || null, recon_explained: value }),
      });
      setError(null);
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const gap = Number(rec.gap ?? 0);
  return (
    <div class={`recon r-${rec.status}`}>
      <div class="recon-head">
        <b>Kasa fiskalna vs Booksy</b>
        {rec.status === 'no_report' && <span class="rbadge">brak raportu dobowego</span>}
        {rec.status === 'ok' && <span class="rbadge ok">zgadza się</span>}
        {rec.status === 'explained' && <span class="rbadge ok">różnica wyjaśniona</span>}
        {rec.status === 'gap' && (
          <span class="rbadge bad">
            różnica {gap > 0 ? '+' : '−'}
            {pln(Math.abs(gap))} zł
          </span>
        )}
      </div>

      {rec.status === 'no_report' && (
        <p class="muted small">
          Wpisz powyżej sumę z raportu dobowego drukarki fiskalnej — system porówna ją z tym, co rozliczono w Booksy
          ({pln(rec.booksy_till)} zł){!rec.synced && ' — uwaga: transakcje z Booksy dla tego dnia nie są jeszcze zsynchronizowane'}.
        </p>
      )}

      {(rec.status === 'gap' || rec.status === 'explained') && (
        <div>
          <p class="small">
            Booksy: <b>{pln(rec.booksy_till)} zł</b> · drukarka fiskalna: <b>{pln(rec.fiscal_printer_total ?? 0)} zł</b>.{' '}
            {gap > 0
              ? 'W Booksy rozliczono więcej, niż nabito na kasę — któraś wizyta nie przeszła przez kasę fiskalną.'
              : 'Na kasie nabito więcej, niż rozliczono w Booksy — sprzedaż bez rozliczenia wizyty w Booksy?'}
          </p>

          {isAdmin && gap > 0 && rec.candidates.length > 0 && (
            <div>
              <span class="klbl">Transakcje pasujące kwotą do różnicy</span>
              {rec.candidates.map((group, i) => (
                <ul class="cand" key={i}>
                  {group.map((t, j) => (
                    <li key={j}>
                      <b>{pln(t.amount)} zł</b> · {t.client || '—'} · wykonała:{' '}
                      <b>{t.performer ?? 'nieustalone'}</b> · {t.method}
                      {t.doc && <span class="muted small"> · {t.doc}</span>}
                    </li>
                  ))}
                </ul>
              ))}
            </div>
          )}
          {isAdmin && gap > 0 && rec.candidates.length === 0 && (
            <p class="muted small">
              {rec.synced
                ? 'Żadna pojedyncza transakcja ani para nie daje dokładnie tej kwoty — sprawdź listę poniżej.'
                : 'Brak zsynchronizowanych transakcji z Booksy dla tego dnia — uruchom synchronizację kasy.'}
            </p>
          )}
          {!isAdmin && <p class="muted small">Zgłoś różnicę właścicielce — szczegóły widzi administrator.</p>}

          {isAdmin && (
            <div class="recon-explain">
              <input
                class="fld"
                placeholder="wyjaśnienie (np. nabite następnego dnia, paragon nr…)"
                value={note}
                onInput={(e) => setNote((e.target as HTMLInputElement).value)}
              />
              {rec.status === 'gap' ? (
                <button class="btn" onClick={() => explain(true)}>
                  Oznacz jako wyjaśnione
                </button>
              ) : (
                <button class="btn" onClick={() => explain(false)}>
                  Cofnij wyjaśnienie
                </button>
              )}
            </div>
          )}

          {isAdmin && rec.transactions.length > 0 && (
            <details>
              <summary class="small">Wszystkie transakcje Booksy tego dnia ({rec.transactions.length})</summary>
              <ul class="cand">
                {rec.transactions.map((t, j) => (
                  <li key={j}>
                    {pln(t.amount)} zł · {t.client || '—'} · {t.performer ?? '—'} · {t.method}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
