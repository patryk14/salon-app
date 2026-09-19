// The shop as a client sees it (F11): browse home-care products, order for pickup
// at the salon (no online payment — she pays at the desk), follow her orders.
// Exact stock figures are never shown; ordering reserves the items for her.
import { useEffect, useState } from 'preact/hooks';
import { apiFetch } from '../lib/api';

interface Product {
  id: number;
  name: string;
  brand: string | null;
  description: string | null;
  price_pln: string;
  available: boolean;
  low_stock: boolean;
}
interface Order {
  id: number;
  status: string;
  note: string | null;
  created_at: string;
  total: string;
  items: { product_name: string; qty: number; price_at_order: string }[];
}

const STATUS: Record<string, [string, string]> = {
  placed: ['przyjęte — przygotowujemy', 's-scheduled'],
  ready: ['gotowe do odbioru', 's-active'],
  picked_up: ['odebrane', 's-completed'],
  cancelled: ['anulowane', 's-cancelled'],
};
const pln = (v: string | number) =>
  Number(v).toLocaleString('pl-PL', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function KlientShop() {
  const [products, setProducts] = useState<Product[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [cart, setCart] = useState<Record<number, number>>({});
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    const [p, o] = await Promise.all([
      apiFetch<Product[]>('/klient/shop/products'),
      apiFetch<Order[]>('/klient/me/orders'),
    ]);
    setProducts(p);
    setOrders(o);
  }
  useEffect(() => {
    load().catch(() => {
      /* the shop is an extra — a failure here must not break the profile */
    });
  }, []);

  const setQty = (id: number, qty: number) =>
    setCart((c) => {
      const next = { ...c };
      if (qty <= 0) delete next[id];
      else next[id] = Math.min(qty, 20);
      return next;
    });

  const lines = products.filter((p) => cart[p.id]);
  const total = lines.reduce((a, p) => a + Number(p.price_pln) * cart[p.id], 0);

  async function placeOrder() {
    if (lines.length === 0) return;
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      await apiFetch('/klient/me/orders', {
        method: 'POST',
        body: JSON.stringify({
          items: lines.map((p) => ({ product_id: p.id, qty: cart[p.id] })),
          note: note.trim() || null,
        }),
      });
      setCart({});
      setNote('');
      setInfo('Zamówienie przyjęte — damy znać, gdy będzie gotowe do odbioru. Płatność przy odbiorze w salonie.');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      await load().catch(() => {});
    } finally {
      setBusy(false);
    }
  }

  async function cancel(o: Order) {
    if (!confirm('Anulować to zamówienie?')) return;
    setError(null);
    try {
      await apiFetch(`/klient/me/orders/${o.id}/cancel`, { method: 'POST' });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  if (products.length === 0 && orders.length === 0) return null;

  return (
    <section>
      <div class="shead">
        <h3>Sklep</h3>
        <span class="muted small">odbiór i płatność w salonie</span>
      </div>
      {error && <div class="err">{error}</div>}
      {info && <div class="okmsg">{info}</div>}

      <div class="shop">
        {products.map((p) => (
          <div class={`sitem${p.available ? '' : ' out'}`} key={p.id}>
            <div class="sname">
              {p.name}
              {p.brand && <span class="muted small"> · {p.brand}</span>}
            </div>
            {p.description && <div class="muted small">{p.description}</div>}
            <div class="srow">
              <b>{pln(p.price_pln)} zł</b>
              {!p.available ? (
                <span class="badge s-cancelled">chwilowo brak</span>
              ) : cart[p.id] ? (
                <span class="qty">
                  <button class="qbtn" onClick={() => setQty(p.id, cart[p.id] - 1)} aria-label="mniej">
                    −
                  </button>
                  <b>{cart[p.id]}</b>
                  <button class="qbtn" onClick={() => setQty(p.id, cart[p.id] + 1)} aria-label="więcej">
                    +
                  </button>
                </span>
              ) : (
                <button class="btn sm" onClick={() => setQty(p.id, 1)}>
                  Dodaj
                </button>
              )}
            </div>
            {p.available && p.low_stock && <span class="muted small">ostatnie sztuki</span>}
          </div>
        ))}
      </div>

      {lines.length > 0 && (
        <div class="cartbox">
          <b>Twoje zamówienie — {pln(total)} zł</b>
          <ul>
            {lines.map((p) => (
              <li key={p.id}>
                {p.name} × {cart[p.id]}
              </li>
            ))}
          </ul>
          <input
            placeholder="uwagi (opcjonalnie), np. odbiorę przy wizycie w piątek"
            value={note}
            maxLength={500}
            onInput={(e) => setNote((e.target as HTMLInputElement).value)}
          />
          <button class="btn primary" disabled={busy} onClick={placeOrder}>
            {busy ? 'Wysyłanie…' : 'Zamawiam z odbiorem w salonie'}
          </button>
        </div>
      )}

      {orders.length > 0 && (
        <div class="myorders">
          <span class="lbl">Moje zamówienia</span>
          {orders.map((o) => {
            const [label, cls] = STATUS[o.status] ?? [o.status, ''];
            return (
              <div class="orow" key={o.id}>
                <div>
                  <span class={`badge ${cls}`}>{label}</span>{' '}
                  <span class="muted small">
                    {new Date(o.created_at).toLocaleDateString('pl-PL')} · {pln(o.total)} zł
                  </span>
                  <div class="small">{o.items.map((i) => `${i.product_name} × ${i.qty}`).join(', ')}</div>
                </div>
                {o.status === 'placed' && (
                  <button class="link" onClick={() => cancel(o)}>
                    anuluj
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
