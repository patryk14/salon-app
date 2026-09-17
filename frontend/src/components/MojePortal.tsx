// Client portal (F7) — a client's OWN view: profile, visit history, packages and
// vouchers. Row-scoped by the backend to the token's client (the /klient/me/*
// endpoints); this UI never sends a client id. Before the account is linked it
// shows the invite-claim box (the owner hands out a code in the salon).
import { useEffect, useState } from 'preact/hooks';
import { getUser, groupsOf, login, logout } from '../lib/auth';
import { apiFetch } from '../lib/api';

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

export default function MojePortal() {
  const [ready, setReady] = useState(false);
  const [isClient, setIsClient] = useState(false);
  const [me, setMe] = useState<Me | null>(null);
  const [month, setMonth] = useState(thisMonth());
  const [visits, setVisits] = useState<Visit[]>([]);
  const [pkgs, setPkgs] = useState<Pkg[]>([]);
  const [vouchers, setVouchers] = useState<Voucher[]>([]);
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
      const [v, p, vo] = await Promise.all([
        apiFetch<Visit[]>(`/klient/me/visits?month=${month}`),
        apiFetch<Pkg[]>('/klient/me/packages'),
        apiFetch<Voucher[]>('/klient/me/vouchers'),
      ]);
      setVisits(v);
      setPkgs(p);
      setVouchers(vo);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (me?.linked) loadData();
  }, [me?.linked, month]);

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
        <p class="muted">Zaloguj się, aby zobaczyć swoje wizyty, pakiety i vouchery.</p>
        <button class="btn primary" onClick={() => login()}>
          Zaloguj się
        </button>
        <p class="muted small">
          Pierwszy raz? Kliknij powyżej i wybierz <b>„Zarejestruj się"</b> na stronie logowania —
          jeśli masz u nas maila, konto połączy się z Twoim profilem automatycznie.
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
