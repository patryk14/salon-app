// Client portal (F7) — a client's OWN view: profile, visit history, packages and
// vouchers. Row-scoped by the backend to the token's client (the /klient/me/*
// endpoints); this UI never sends a client id. Before the account is linked it
// shows the invite-claim box (the owner hands out a code in the salon).
import { useEffect, useState } from 'preact/hooks';
import { getUser, groupsOf, login, logout, signup } from '../lib/auth';
import { apiFetch } from '../lib/api';
import AuthImage from './AuthImage';

interface Me {
  linked: boolean;
  client_id: number | null;
  first_name: string | null;
  last_name: string | null;
  phone: string | null;
  email: string | null;
  total_visits: number;
  first_visit: string | null;
  last_visit: string | null;
}
interface Visit {
  id: number;
  starts_at: string;
  service_name: string;
  staff_name: string | null;
  price_pln: string | null;
  status: string;
}
interface Pkg {
  name: string;
  total_treatments: number;
  remaining: number;
  valid_until: string | null;
  status: string;
}
interface Voucher {
  description: string;
  total_value: string;
  remaining_value: string;
  valid_until: string | null;
  status: string;
}
interface Photo {
  id: number;
  kind: 'before' | 'after' | null;
  note: string | null;
  taken_on: string | null;
}
interface PlanStep {
  id: number;
  treatment: string;
  sessions_planned: number;
  sessions_done: number;
  interval_note: string | null;
}
interface BeautyPlan {
  updated_at: string;
  steps: PlanStep[];
  [section: string]: unknown;
}
interface Aftercare {
  treatment: string;
  aftercare: string;
  last_session: string | null;
}
// The printed booklet's layout: morning / evening, then the free-text sections.
const PLAN_ROUTINE: [string, string, string, string][] = [
  ['am_cleansing', 'Oczyszczanie', 'pm_cleansing', 'Oczyszczanie'],
  ['am_antioxidant', 'Antyoksydacja', 'pm_therapeutic', 'Działanie terapeutyczne'],
  ['am_hydration', 'Nawilżenie', 'pm_serum', 'Serum'],
  ['am_spf', 'Krem z filtrem SPF', 'pm_cream', 'Krem pielęgnacyjny'],
];
const PLAN_SECTIONS: [string, string][] = [
  ['extra_care', 'Pielęgnacja dodatkowa'],
  ['lifestyle', 'Suplementacja, styl życia'],
  ['recommendations', 'Dodatkowe zalecenia'],
];
interface Rebook {
  service: string;
  last_visit: string;
  interval_days: number;
  suggested_next: string;
  due: boolean;
  recommendation: string | null;
}

const pln = (v: string) => Number(v).toLocaleString('pl-PL', { maximumFractionDigits: 0 });
const STATUS_PL: Record<string, string> = {
  completed: 'Zakończona',
  cancelled: 'Anulowana',
  no_show: 'Nieobecność',
  scheduled: 'Zaplanowana',
  active: 'aktywny',
  used: 'wykorzystany',
  used_up: 'wykorzystany',
  expired: 'wygasły',
};
const fmtDate = (iso: string) => new Date(iso).toLocaleDateString('pl-PL');
const fmtDateTime = (iso: string) =>
  new Date(iso).toLocaleString('pl-PL', { dateStyle: 'medium', timeStyle: 'short' });
function thisMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

export default function KlientPortal() {
  const [ready, setReady] = useState(false);
  const [isClient, setIsClient] = useState(false);
  const [me, setMe] = useState<Me | null>(null);
  const [month, setMonth] = useState(thisMonth());
  const [visits, setVisits] = useState<Visit[]>([]);
  const [pkgs, setPkgs] = useState<Pkg[]>([]);
  const [vouchers, setVouchers] = useState<Voucher[]>([]);
  const [rebook, setRebook] = useState<Rebook[]>([]);
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [plan, setPlan] = useState<BeautyPlan | null>(null);
  const [aftercare, setAftercare] = useState<Aftercare[]>([]);
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      const user = await getUser();
      if (user && !user.expired) setIsClient(groupsOf(user).includes('client'));
      setReady(true);
    })();
  }, []);

  async function loadMe() {
    setError(null);
    try {
      let me = await apiFetch<Me>('/klient/me');
      // Self-signed-up client: try to auto-link her to her profile by verified
      // email before falling back to the invite-code box.
      if (!me.linked) {
        try {
          me = await apiFetch<Me>('/klient/me/link', { method: 'POST' });
        } catch {
          /* auto-link unavailable → code fallback */
        }
      }
      setMe(me);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (ready && isClient) loadMe();
  }, [ready, isClient]);

  async function loadData() {
    setError(null);
    try {
      const [v, p, vo, rb] = await Promise.all([
        apiFetch<Visit[]>(`/klient/me/visits?month=${month}`),
        apiFetch<Pkg[]>('/klient/me/packages'),
        apiFetch<Voucher[]>('/klient/me/vouchers'),
        apiFetch<Rebook[]>('/klient/me/rebooking'),
      ]);
      setVisits(v);
      setPkgs(p);
      setVouchers(vo);
      setRebook(rb);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (me?.linked) loadData();
  }, [me?.linked, month]);

  // Progress photos don't depend on the month — load once. A failure here must
  // not hide the rest of the profile.
  useEffect(() => {
    if (!me?.linked) return;
    apiFetch<Photo[]>('/klient/me/photos')
      .then(setPhotos)
      .catch(() => setPhotos([]));
    apiFetch<BeautyPlan | null>('/klient/me/beauty-plan')
      .then(setPlan)
      .catch(() => setPlan(null));
    apiFetch<Aftercare[]>('/klient/me/aftercare')
      .then(setAftercare)
      .catch(() => setAftercare([]));
  }, [me?.linked]);

  async function claim() {
    if (!code.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch('/invites/claim', { method: 'POST', body: JSON.stringify({ code: code.trim() }) });
      setCode('');
      await loadMe();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!ready) return <p class="muted">Ładowanie…</p>;

  if (!isClient) {
    return (
      <div class="gate">
        <h2>Twój profil</h2>
        <p class="muted">Zaloguj się lub załóż konto — zobaczysz swoje wizyty, pakiety i vouchery.</p>
        <div class="row">
          <button class="btn primary" onClick={() => login()}>
            Zaloguj się
          </button>
          <button class="btn" onClick={() => signup()}>
            Zarejestruj się
          </button>
        </div>
        <p class="muted small">
          Pierwszy raz? Jeśli masz u nas podany email, konto połączy się z Twoim profilem
          automatycznie. Jeśli nie — dostaniesz kod w salonie.
        </p>
      </div>
    );
  }

  if (me && !me.linked) {
    return (
      <div class="gate">
        <h2>Połącz konto</h2>
        <p class="muted">
          Wpisz kod, który dostałaś w salonie — połączy Twoje konto z Twoim profilem.
        </p>
        {error && <div class="err">{error}</div>}
        <div class="row">
          <input
            placeholder="KOD"
            value={code}
            onInput={(e) => setCode((e.target as HTMLInputElement).value.toUpperCase())}
          />
          <button class="btn primary" disabled={busy} onClick={claim}>
            Połącz
          </button>
        </div>
        <button class="link" onClick={() => logout()}>
          Wyloguj
        </button>
      </div>
    );
  }

  return (
    <div>
      {error && <div class="err">{error}</div>}

      {me && (
        <div class="prof">
          <div>
            <h2>
              {me.first_name} {me.last_name}
            </h2>
            <p class="muted small">
              {me.total_visits} wizyt
              {me.last_visit ? ` · ostatnia ${fmtDate(me.last_visit)}` : ''}
              {me.phone ? ` · ${me.phone}` : ''}
            </p>
          </div>
          <button class="link" onClick={() => logout()}>
            Wyloguj
          </button>
        </div>
      )}

      {rebook.length > 0 && (
        <section>
          <div class="shead">
            <h3>Kolejna wizyta</h3>
          </div>
          <div class="cards">
            {rebook.map((r) => (
              <div class={`card${r.due ? ' due' : ''}`}>
                <div class="card-t">{r.service}</div>
                <div class="card-big" style="font-size:1.1rem">
                  {r.due ? 'Czas na wizytę' : fmtDate(r.suggested_next)}
                </div>
                <div class="muted small">
                  {r.due ? `sugerowana od ${fmtDate(r.suggested_next)}` : 'sugerowany termin'}
                  {r.recommendation ? ` · ${r.recommendation}` : ''}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section>
        <div class="shead">
          <h3>Pakiety</h3>
        </div>
        {pkgs.length === 0 ? (
          <p class="muted small">Brak aktywnych pakietów.</p>
        ) : (
          <div class="cards">
            {pkgs.map((p) => (
              <div class="card">
                <div class="card-t">{p.name}</div>
                <div class="card-big">
                  {p.remaining}
                  <span class="muted"> / {p.total_treatments}</span>
                </div>
                <div class="muted small">
                  <span class={`badge s-${p.status}`}>{STATUS_PL[p.status] ?? p.status}</span>
                  {p.valid_until ? ` · do ${fmtDate(p.valid_until)}` : ''}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <div class="shead">
          <h3>Vouchery</h3>
        </div>
        {vouchers.length === 0 ? (
          <p class="muted small">Brak voucherów.</p>
        ) : (
          <div class="cards">
            {vouchers.map((v) => (
              <div class="card">
                <div class="card-t">{v.description}</div>
                <div class="card-big">
                  {pln(v.remaining_value)}
                  <span class="muted"> / {pln(v.total_value)} zł</span>
                </div>
                <div class="muted small">
                  <span class={`badge s-${v.status}`}>{STATUS_PL[v.status] ?? v.status}</span>
                  {v.valid_until ? ` · do ${fmtDate(v.valid_until)}` : ''}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {plan && (
        <section>
          <div class="shead">
            <h3>Mój Beauty Plan</h3>
            <span class="muted small">aktualizacja {fmtDate(plan.updated_at)}</span>
          </div>
          {typeof plan.skin_type === 'string' && plan.skin_type && (
            <p>
              <b>Typ skóry:</b> {plan.skin_type}
            </p>
          )}
          {PLAN_ROUTINE.some(([am, , pm]) => plan[am] || plan[pm]) && (
            <div class="routine">
              <div class="rhead">Rano</div>
              <div class="rhead">Wieczorem</div>
              {PLAN_ROUTINE.map(([am, amLabel, pm, pmLabel]) => [
                <div class="rcell" key={am}>
                  <span class="lbl">{amLabel}</span>
                  <div class="pre">{(plan[am] as string | null) || '—'}</div>
                </div>,
                <div class="rcell" key={pm}>
                  <span class="lbl">{pmLabel}</span>
                  <div class="pre">{(plan[pm] as string | null) || '—'}</div>
                </div>,
              ])}
            </div>
          )}
          {PLAN_SECTIONS.map(([key, label]) =>
            plan[key] ? (
              <div class="psec" key={key}>
                <span class="lbl">{label}</span>
                <div class="pre">{plan[key] as string}</div>
              </div>
            ) : null,
          )}
          {plan.steps.length > 0 && (
            <div class="psec">
              <span class="lbl">Plan zabiegowy</span>
              {plan.steps.map((s) => {
                const pct = Math.min(100, Math.round((s.sessions_done / s.sessions_planned) * 100));
                return (
                  <div class="pstep" key={s.id}>
                    <div class="pstep-head">
                      <span>
                        {s.treatment}
                        {s.interval_note && <span class="muted small"> · {s.interval_note}</span>}
                      </span>
                      <b>
                        {s.sessions_done} / {s.sessions_planned}
                      </b>
                    </div>
                    <div class="pbar">
                      <div class="pbar-fill" style={`width:${pct}%`} />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      )}

      {aftercare.length > 0 && (
        <section>
          <div class="shead">
            <h3>Zalecenia po zabiegu</h3>
          </div>
          {aftercare.map((a) => (
            <details class="after" key={a.treatment}>
              <summary>
                {a.treatment}
                {a.last_session && <span class="muted small"> · ostatni zabieg {fmtDate(a.last_session)}</span>}
              </summary>
              <ul>
                {a.aftercare.split('\n').map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </details>
          ))}
        </section>
      )}

      {photos.length > 0 && (
        <section>
          <div class="shead">
            <h3>Zdjęcia postępów</h3>
            <span class="muted small">prywatne — widzisz je tylko Ty i salon</span>
          </div>
          <div class="pgrid">
            {photos.map((p) => (
              <figure key={p.id}>
                <AuthImage path={`/klient/me/photos/${p.id}/content`} alt={p.note ?? 'zdjęcie postępów'} />
                <figcaption>
                  {p.kind && <span class={`badge k-${p.kind}`}>{p.kind === 'before' ? 'Przed' : 'Po'}</span>}{' '}
                  <span class="muted small">{p.taken_on ? fmtDate(p.taken_on) : ''}</span>
                  {p.note && <div class="small">{p.note}</div>}
                </figcaption>
              </figure>
            ))}
          </div>
        </section>
      )}

      <section>
        <div class="shead">
          <h3>Wizyty</h3>
          <input type="month" value={month} onChange={(e) => setMonth((e.target as HTMLInputElement).value)} />
        </div>
        <div class="scroll">
          <table>
            <tbody>
              {visits.map((v) => (
                <tr key={v.id}>
                  <td class="nowrap">{fmtDateTime(v.starts_at)}</td>
                  <td>{v.service_name}</td>
                  <td class="muted small">{v.staff_name ?? ''}</td>
                  <td>
                    <span class={`badge s-${v.status}`}>{STATUS_PL[v.status] ?? v.status}</span>
                  </td>
                </tr>
              ))}
              {visits.length === 0 && (
                <tr>
                  <td colSpan={4} class="muted" style="text-align:center;padding:1.2rem">
                    Brak wizyt w tym miesiącu.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
