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
  status: 'no_report' | 'not_synced' | 'ok' | 'gap' | 'explained';
  booksy_till: string;
  shop_sales: string;
  fiscal_printer_total: string | null;
  gap: string | null;
  recon_note: string | null;
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
        setNote(r.recon_note ?? '');
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
      // admin-only endpoint; the explanation is pinned to the CURRENT gap amount
      await apiFetch(`/salon-days/${day}/reconciliation/explain`, {
        method: 'POST',
        body: JSON.stringify({ explained: value, note: note.trim() || null }),
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
        {rec.status === 'not_synced' && <span class="rbadge">czeka na synchronizację Booksy</span>}
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

      {rec.status === 'not_synced' && (
        <p class="muted small">
          Raport dobowy jest wpisany ({pln(rec.fiscal_printer_total ?? 0)} zł), ale nie mamy jeszcze kasy z Booksy dla tego
          dnia — porównanie pojawi się po synchronizacji kasy (Booksy → „Kasa").
        </p>
      )}

      {(rec.status === 'gap' || rec.status === 'explained') && (
        <div>
          <p class="small">
            Booksy: <b>{pln(rec.booksy_till)} zł</b>
            {Number(rec.shop_sales) > 0 && (
              <span>
                {' '}
                + sklep: <b>{pln(rec.shop_sales)} zł</b>
              </span>
            )}{' '}
            · drukarka fiskalna: <b>{pln(rec.fiscal_printer_total ?? 0)} zł</b>.{' '}
            {gap > 0
              ? 'Rozliczono więcej, niż nabito na kasę — któraś wizyta lub sprzedaż nie przeszła przez kasę fiskalną.'
              : 'Na kasie nabito więcej, niż rozliczono — wizyta nierozliczona w Booksy albo produkt niesprzedany w appce?'}
          </p>

          {isAdmin && gap > 0 && rec.candidates.length > 0 && (
            <div>
              <span class="klbl">Transakcje pasujące kwotą do różnicy</span>
              {rec.candidates.map((group, i) => (
                <ul class="cand" key={i}>
                  {group.map((t, j) => (
                    <li key={j}>
                      <b>{pln(t.amount)} zł</b> · {t.client || (t.method?.startsWith('sklep') ? 'sprzedaż w sklepie' : '—')} ·{' '}
                      {t.method?.startsWith('sklep') ? 'sprzedała' : 'wykonała'}: <b>{t.performer ?? 'nieustalone'}</b> ·{' '}
                      {t.method}
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
              <summary class="small">Wszystkie transakcje tego dnia — Booksy i sklep ({rec.transactions.length})</summary>
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
