// Shop (F11, staff & admin): the product list with a real shelf, quick sales that
// feed the seller's SALES commission, and the pickup orders clients place from
// their portal. Staff always sell as themselves (the API takes the seller from
// the token); only an admin picks who a sale is credited to.
import { useEffect, useState } from 'preact/hooks';
import { getUser, groupsOf, login } from '../lib/auth';
import { apiFetch } from '../lib/api';

interface Product {
  id: number;
  name: string;
  brand: string | null;
  description: string | null;
  price_pln: string;
  stock_qty: number;
  active: boolean;
}
interface Movement {
  id: number;
  delta: number;
  reason: string;
  ref: string | null;
  note: string | null;
  created_by_name: string | null;
  created_at: string;
}
interface Sale {
  id: number;
  product_name: string;
  qty: number;
  total: string;
  sold_on: string;
  payment_method: string;
  employee_name: string | null;
  order_id: number | null;
  created_by_sub: string | null;
}
interface OrderItem {
  product_name: string;
  qty: number;
  price_at_order: string;
}
interface Order {
  id: number;
  client_name: string | null;
  status: string;
  note: string | null;
  created_at: string;
  items: OrderItem[];
  total: string;
}
interface Employee {
  id: number;
  display_name: string;
  is_active: boolean;
}

type Tab = 'products' | 'sales' | 'orders';
const PAY: Record<string, string> = { karta: 'Karta', gotowka: 'Gotówka', inne: 'Inne' };
const REASON: Record<string, string> = {
  delivery: 'dostawa',
  sale: 'sprzedaż',
  correction: 'korekta',
  order: 'rezerwacja (zamówienie)',
  order_cancel: 'zwolnienie rezerwacji',
};
const ORDER_STATUS: Record<string, string> = { placed: 'nowe', ready: 'gotowe do odbioru' };

const pln = (v: string | number) =>
  Number(v).toLocaleString('pl-PL', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export default function ShopView() {
  const [ready, setReady] = useState(false);
  const [isStaff, setIsStaff] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [mySub, setMySub] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>('products');
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [products, setProducts] = useState<Product[]>([]);
  const [showRetired, setShowRetired] = useState(false);
  const [newP, setNewP] = useState({ name: '', brand: '', price_pln: '', stock_qty: '' });
  const [history, setHistory] = useState<{ id: number; rows: Movement[] } | null>(null);

  const [month, setMonth] = useState(today().slice(0, 7));
  const [sales, setSales] = useState<Sale[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [sell, setSell] = useState({ product_id: '', qty: '1', payment_method: 'karta', employee_id: '', sold_on: today() });

  const [orders, setOrders] = useState<Order[]>([]);
  const [pickup, setPickup] = useState<Record<number, { payment_method: string; employee_id: string }>>({});

  useEffect(() => {
    (async () => {
      const user = await getUser();
      if (user && !user.expired) {
        const g = groupsOf(user);
        setIsStaff(g.includes('staff') || g.includes('admin'));
        setIsAdmin(g.includes('admin'));
        setMySub(user.profile.sub);
      }
      setReady(true);
    })();
  }, []);

  // `guard`: money-moving actions are serialized — a second click while the first
  // request is still in flight (Aurora can take ~15 s to wake) must not fire again.
  // The API is atomic anyway; this just spares the user a confusing 409.
  async function run(job: () => Promise<unknown>, ok?: string, guard = false) {
    if (guard && busy) return;
    setError(null);
    setInfo(null);
    if (guard) setBusy(true);
    try {
      await job();
      if (ok) setInfo(ok);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (guard) setBusy(false);
    }
  }

  const loadProducts = () =>
    run(async () => setProducts(await apiFetch<Product[]>(`/shop/products?include_inactive=${showRetired}`)));
  const loadSales = () => run(async () => setSales(await apiFetch<Sale[]>(`/shop/sales?month=${month}`)));
  const loadOrders = () => run(async () => setOrders(await apiFetch<Order[]>('/shop/orders')));

  useEffect(() => {
    if (ready && isStaff) loadProducts();
  }, [ready, isStaff, showRetired]);
  useEffect(() => {
    if (ready && isStaff) loadSales();
  }, [ready, isStaff, month]);
  useEffect(() => {
    if (!ready || !isStaff) return;
    loadOrders();
    // the seller picker is an admin-only control (staff always sell as themselves)
    if (isAdmin)
      apiFetch<Employee[]>('/employees')
        .then((e) => setEmployees(e.filter((x) => x.is_active)))
        .catch(() => {});
  }, [ready, isStaff, isAdmin]);

  // ---- products
  const addProduct = () =>
    run(async () => {
      if (!newP.name.trim() || newP.price_pln === '') throw new Error('Podaj nazwę i cenę.');
      await apiFetch('/shop/products', {
        method: 'POST',
        body: JSON.stringify({
          name: newP.name.trim(),
          brand: newP.brand.trim() || null,
          price_pln: newP.price_pln.replace(',', '.'),
          stock_qty: Number(newP.stock_qty) || 0,
        }),
      });
      setNewP({ name: '', brand: '', price_pln: '', stock_qty: '' });
      await loadProducts();
    }, 'Dodano produkt.');

  const patchProduct = (p: Product, body: Record<string, unknown>) =>
    run(async () => {
      await apiFetch(`/shop/products/${p.id}`, { method: 'PATCH', body: JSON.stringify(body) });
      await loadProducts();
    });

  const changeStock = (p: Product, reason: 'delivery' | 'correction') =>
    run(async () => {
      const label =
        reason === 'delivery'
          ? `Dostawa „${p.name}" — ile sztuk przyjęto?`
          : `Korekta stanu „${p.name}" (jest ${p.stock_qty}). Podaj zmianę, np. -1 albo 2:`;
      const raw = prompt(label);
      if (raw === null || raw.trim() === '') return;
      const delta = Number(raw.replace(',', '.'));
      if (!Number.isInteger(delta) || delta === 0) throw new Error('Podaj liczbę całkowitą różną od zera.');
      const note = reason === 'correction' ? prompt('Powód korekty (np. stłuczony, inwentaryzacja):') : null;
      await apiFetch(`/shop/products/${p.id}/stock`, {
        method: 'POST',
        body: JSON.stringify({ delta, reason, note: note?.trim() || null }),
      });
      await loadProducts();
      if (history?.id === p.id) await showHistory(p);
    });

  const removeProduct = (p: Product) =>
    run(async () => {
      if (!confirm(`Usunąć „${p.name}" ze sklepu? Jeśli był już sprzedawany, zostanie tylko wycofany (historia zostaje).`))
        return;
      const r = await apiFetch<{ removed: string }>(`/shop/products/${p.id}`, { method: 'DELETE' });
      setInfo(r.removed === 'retired' ? 'Produkt wycofany — historia sprzedaży zachowana.' : 'Produkt usunięty.');
      await loadProducts();
    });

  async function showHistory(p: Product) {
    if (history?.id === p.id) {
      setHistory(null);
      return;
    }
    await run(async () =>
      setHistory({ id: p.id, rows: await apiFetch<Movement[]>(`/shop/products/${p.id}/movements`) }),
    );
  }

  // ---- sales
  const doSell = () =>
    run(async () => {
      if (!sell.product_id) throw new Error('Wybierz produkt.');
      await apiFetch('/shop/sales', {
        method: 'POST',
        body: JSON.stringify({
          product_id: Number(sell.product_id),
          qty: Math.max(1, Number(sell.qty) || 1),
          payment_method: sell.payment_method,
          // staff always sell "today" (the API enforces it); only an admin back-dates
          ...(isAdmin
            ? { sold_on: sell.sold_on || today(), employee_id: sell.employee_id ? Number(sell.employee_id) : null }
            : {}),
        }),
      });
      setSell({ ...sell, product_id: '', qty: '1' });
      await Promise.all([loadSales(), loadProducts()]);
    }, 'Sprzedaż zapisana.', true);

  const voidSale = (s: Sale) =>
    run(async () => {
      if (!confirm(`Anulować sprzedaż „${s.product_name}" ×${s.qty}? Sztuki wrócą na stan.`)) return;
      await apiFetch(`/shop/sales/${s.id}`, { method: 'DELETE' });
      await Promise.all([loadSales(), loadProducts()]);
    });

  // ---- orders
  const orderAction = (o: Order, action: 'ready' | 'cancel' | 'pickup') =>
    run(async () => {
      if (action === 'cancel' && !confirm(`Anulować zamówienie #${o.id}? Zarezerwowane sztuki wrócą na stan.`)) return;
      const form = pickup[o.id] ?? { payment_method: 'karta', employee_id: '' };
      await apiFetch(`/shop/orders/${o.id}/${action}`, {
        method: 'POST',
        body:
          action === 'pickup'
            ? JSON.stringify({
                payment_method: form.payment_method,
                ...(isAdmin ? { employee_id: form.employee_id ? Number(form.employee_id) : null } : {}),
              })
            : undefined,
      });
      await Promise.all([loadOrders(), loadSales(), loadProducts()]);
    }, undefined, true);

  if (!ready) return <p class="muted">Ładowanie…</p>;
  if (!isStaff) {
    return (
      <div class="gate">
        <h2>Sklep</h2>
        <p class="muted">Zaloguj się, aby kontynuować.</p>
        <button class="btn primary" onClick={() => login()}>
          Zaloguj przez Cognito
        </button>
      </div>
    );
  }

  const sellable = products.filter((p) => p.active && p.stock_qty > 0);
  const salesTotal = sales.reduce((a, s) => a + Number(s.total), 0);
  const sellerSelect = (value: string, onChange: (v: string) => void) => (
    <select value={value} onChange={(e) => onChange((e.target as HTMLSelectElement).value)} title="Komu liczy się prowizja">
      <option value="">bez prowizji (właścicielka)</option>
      {employees.map((e) => (
        <option key={e.id} value={e.id}>
          {e.display_name}
        </option>
      ))}
    </select>
  );

  return (
    <div>
      {error && <div class="err">{error}</div>}
      {info && <div class="ok">{info}</div>}

      <div class="tabs">
        {(
          [
            ['products', `Produkty (${products.filter((p) => p.active).length})`],
            ['sales', 'Sprzedaż'],
            ['orders', `Zamówienia klientek (${orders.length})`],
          ] as const
        ).map(([key, label]) => (
          <button key={key} class={`tab${tab === key ? ' active' : ''}`} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </div>

      {tab === 'products' && (
        <div>
          <div class="scroll">
            <table>
              <thead>
                <tr>
                  <th>Produkt</th>
                  <th>Marka</th>
                  <th class="amt">Cena</th>
                  <th class="amt">Stan</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {products.map((p) => [
                  <tr key={p.id} class={p.active ? '' : 'retired'}>
                    <td>
                      {p.name} {!p.active && <span class="badge">wycofany</span>}
                    </td>
                    <td class="muted small">{p.brand ?? ''}</td>
                    <td class="amt">
                      <input
                        class="cell num"
                        inputMode="decimal"
                        defaultValue={p.price_pln}
                        onBlur={(e) => {
                          const v = (e.target as HTMLInputElement).value.replace(',', '.').trim();
                          if (v && Number(v) !== Number(p.price_pln)) patchProduct(p, { price_pln: v });
                        }}
                      />
                    </td>
                    <td class="amt">
                      <b class={p.stock_qty === 0 ? 'neg' : p.stock_qty <= 2 ? 'warn' : ''}>{p.stock_qty}</b>
                    </td>
                    <td class="actions">
                      {p.active && (
                        <button class="btn sm" onClick={() => changeStock(p, 'delivery')}>
                          + dostawa
                        </button>
                      )}
                      <button class="btn sm" onClick={() => changeStock(p, 'correction')}>
                        korekta
                      </button>
                      <button class="btn sm" onClick={() => showHistory(p)}>
                        historia
                      </button>
                      {p.active ? (
                        <button class="link danger" onClick={() => removeProduct(p)}>
                          usuń
                        </button>
                      ) : (
                        <button class="link" onClick={() => patchProduct(p, { active: true })}>
                          przywróć
                        </button>
                      )}
                    </td>
                  </tr>,
                  history?.id === p.id && (
                    <tr key={`h${p.id}`} class="hist">
                      <td colSpan={5}>
                        {history.rows.length === 0 && <span class="muted small">Brak ruchów.</span>}
                        <ul>
                          {history.rows.map((m) => (
                            <li key={m.id}>
                              <b>{m.delta > 0 ? `+${m.delta}` : m.delta}</b> · {REASON[m.reason] ?? m.reason}
                              {m.note && ` — ${m.note}`}{' '}
                              <span class="muted small">
                                · {m.created_by_name ?? '—'} · {m.created_at.slice(0, 16).replace('T', ' ')}
                                {m.ref && ` · ${m.ref}`}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </td>
                    </tr>
                  ),
                ])}
                {products.length === 0 && (
                  <tr>
                    <td colSpan={5} class="muted empty">
                      Sklep jest pusty — dodaj pierwszy produkt poniżej.
                    </td>
                  </tr>
                )}
                <tr class="add">
                  <td>
                    <input
                      placeholder="nazwa produktu"
                      value={newP.name}
                      onInput={(e) => setNewP({ ...newP, name: (e.target as HTMLInputElement).value })}
                    />
                  </td>
                  <td>
                    <input
                      placeholder="marka"
                      value={newP.brand}
                      onInput={(e) => setNewP({ ...newP, brand: (e.target as HTMLInputElement).value })}
                    />
                  </td>
                  <td class="amt">
                    <input
                      class="num"
                      inputMode="decimal"
                      placeholder="cena"
                      value={newP.price_pln}
                      onInput={(e) => setNewP({ ...newP, price_pln: (e.target as HTMLInputElement).value })}
                    />
                  </td>
                  <td class="amt">
                    <input
                      class="num"
                      type="number"
                      min="0"
                      placeholder="szt."
                      value={newP.stock_qty}
                      onInput={(e) => setNewP({ ...newP, stock_qty: (e.target as HTMLInputElement).value })}
                    />
                  </td>
                  <td>
                    <button class="btn primary sm" onClick={addProduct}>
                      Dodaj produkt
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <label class="chk">
            <input type="checkbox" checked={showRetired} onChange={(e) => setShowRetired((e.target as HTMLInputElement).checked)} />
            pokaż wycofane
          </label>
        </div>
      )}

      {tab === 'sales' && (
        <div>
          <div class="card sellbox">
            <select value={sell.product_id} onChange={(e) => setSell({ ...sell, product_id: (e.target as HTMLSelectElement).value })}>
              <option value="">wybierz produkt…</option>
              {sellable.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} — {pln(p.price_pln)} zł (stan {p.stock_qty})
                </option>
              ))}
            </select>
            <input
              class="num"
              type="number"
              min="1"
              title="Ilość"
              value={sell.qty}
              onInput={(e) => setSell({ ...sell, qty: (e.target as HTMLInputElement).value })}
            />
            <select value={sell.payment_method} onChange={(e) => setSell({ ...sell, payment_method: (e.target as HTMLSelectElement).value })}>
              {Object.entries(PAY).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
            {isAdmin && (
              <input
                type="date"
                max={today()}
                title="Data sprzedaży (tylko administrator może wpisać sprzedaż wstecz)"
                value={sell.sold_on}
                onInput={(e) => setSell({ ...sell, sold_on: (e.target as HTMLInputElement).value })}
              />
            )}
            {isAdmin && sellerSelect(sell.employee_id, (v) => setSell({ ...sell, employee_id: v }))}
            <button class="btn primary" disabled={busy} onClick={doSell}>
              {busy ? 'Zapisywanie…' : 'Sprzedaj'}
            </button>
          </div>
          <p class="muted small">
            {isAdmin
              ? 'Sprzedaż liczy się do prowizji wskazanej osoby (10% od całości, gdy sprzedaż w miesiącu sięgnie 1500 zł).'
              : 'Sprzedaż zapisuje się na Ciebie i liczy do Twojej prowizji (10% od całości, gdy w miesiącu sięgniesz 1500 zł).'}{' '}
            Pamiętaj o nabiciu na kasę fiskalną — sprzedaż kartą/gotówką wchodzi do dziennego uzgodnienia kasy.
          </p>

          <div class="cat-head">
            <h2>
              {isAdmin ? 'Sprzedaż' : 'Moja sprzedaż'} — {pln(salesTotal)} zł
            </h2>
            <input type="month" value={month} onChange={(e) => setMonth((e.target as HTMLInputElement).value)} />
          </div>
          <div class="scroll">
            <table>
              <thead>
                <tr>
                  <th>Data</th>
                  <th>Produkt</th>
                  <th class="amt">Szt.</th>
                  <th class="amt">Kwota</th>
                  <th>Płatność</th>
                  {isAdmin && <th>Sprzedała</th>}
                  <th />
                </tr>
              </thead>
              <tbody>
                {sales.map((s) => (
                  <tr key={s.id}>
                    <td class="nowrap">{s.sold_on}</td>
                    <td>
                      {s.product_name}
                      {s.order_id && <span class="muted small"> · zamówienie #{s.order_id}</span>}
                    </td>
                    <td class="amt">{s.qty}</td>
                    <td class="amt">{pln(s.total)}</td>
                    <td>{PAY[s.payment_method] ?? s.payment_method}</td>
                    {isAdmin && <td>{s.employee_name ?? <span class="muted">—</span>}</td>}
                    <td>
                      {(isAdmin || (s.created_by_sub === mySub && s.sold_on === today())) && (
                        <button class="link danger" onClick={() => voidSale(s)}>
                          anuluj
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {sales.length === 0 && (
                  <tr>
                    <td colSpan={isAdmin ? 7 : 6} class="muted empty">
                      Brak sprzedaży w tym miesiącu.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === 'orders' && (
        <div>
          <p class="muted small">
            Zamówienia złożone przez klientki w ich profilu — odbiór i płatność w salonie. Towar jest zarezerwowany od
            chwili złożenia; „Wydane" zapisuje sprzedaż na osobę wydającą.
          </p>
          {orders.length === 0 && <p class="muted">Brak otwartych zamówień.</p>}
          {orders.map((o) => {
            const form = pickup[o.id] ?? { payment_method: 'karta', employee_id: '' };
            return (
              <div class="card order" key={o.id}>
                <div class="cat-head">
                  <h2>
                    #{o.id} · {o.client_name ?? '—'}{' '}
                    <span class={`badge ${o.status === 'ready' ? 'ok' : 'warn'}`}>{ORDER_STATUS[o.status] ?? o.status}</span>
                  </h2>
                  <span class="muted small">
                    {o.created_at.slice(0, 16).replace('T', ' ')} · <b>{pln(o.total)} zł</b>
                  </span>
                </div>
                <ul>
                  {o.items.map((i, k) => (
                    <li key={k}>
                      {i.product_name} × {i.qty} <span class="muted small">({pln(i.price_at_order)} zł/szt.)</span>
                    </li>
                  ))}
                </ul>
                {o.note && <p class="small">Uwagi klientki: {o.note}</p>}
                <div class="bar">
                  {o.status === 'placed' && (
                    <button class="btn" onClick={() => orderAction(o, 'ready')}>
                      Gotowe do odbioru
                    </button>
                  )}
                  <select
                    value={form.payment_method}
                    onChange={(e) =>
                      setPickup({ ...pickup, [o.id]: { ...form, payment_method: (e.target as HTMLSelectElement).value } })
                    }
                  >
                    {Object.entries(PAY).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </select>
                  {isAdmin &&
                    sellerSelect(form.employee_id, (v) => setPickup({ ...pickup, [o.id]: { ...form, employee_id: v } }))}
                  <button class="btn primary" disabled={busy} onClick={() => orderAction(o, 'pickup')}>
                    {busy ? 'Zapisywanie…' : 'Wydane (zapłacone)'}
                  </button>
                  <button class="link danger" onClick={() => orderAction(o, 'cancel')}>
                    anuluj zamówienie
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
