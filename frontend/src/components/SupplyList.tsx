// Supply list (Day 1) — the salon's internal shopping list. Shared: any staff
// or admin adds items and ticks them off. Not row-scoped, not the customer shop.
import { useEffect, useState } from 'preact/hooks';
import { getUser, groupsOf, login } from '../lib/auth';
import { apiFetch } from '../lib/api';

interface Item {
  id: number;
  name: string;
  status: string;
  note: string | null;
  created_by: string | null;
  bought_at: string | null;
}

export default function SupplyList() {
  const [ready, setReady] = useState(false);
  const [isStaff, setIsStaff] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [items, setItems] = useState<Item[]>([]);
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      const user = await getUser();
      if (user && !user.expired) {
        const g = groupsOf(user);
        setIsStaff(g.includes('staff') || g.includes('admin'));
        setIsAdmin(g.includes('admin'));
      }
      setReady(true);
    })();
  }, []);

  async function load() {
    setError(null);
    try {
      setItems(await apiFetch<Item[]>('/supplies'));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (ready && isStaff) load();
  }, [ready, isStaff]);

  async function add() {
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch('/supplies', { method: 'POST', body: JSON.stringify({ name: name.trim() }) });
      setName('');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function setStatus(item: Item, status: string) {
    try {
      await apiFetch(`/supplies/${item.id}`, { method: 'PATCH', body: JSON.stringify({ status }) });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function remove(id: number) {
    try {
      await apiFetch(`/supplies/${id}`, { method: 'DELETE' });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  if (!ready) return <p class="muted">Ładowanie…</p>;
  if (!isStaff) {
    return (
      <div class="gate">
        <h2>Lista zamówień</h2>
        <p class="muted">Zaloguj się, aby kontynuować.</p>
        <button class="btn primary" onClick={() => login()}>
          Zaloguj przez Cognito
        </button>
      </div>
    );
  }

  const toBuy = items.filter((i) => i.status === 'to_buy');
  const bought = items.filter((i) => i.status === 'bought');

  return (
    <div>
      <div class="bar">
        {/* Role-aware back link: staff must not see that an admin panel exists. */}
        <a class="btn" href={isAdmin ? '/panel' : '/panel/pracownik'}>
          {isAdmin ? '← Panel' : '← Mój portal'}
        </a>
      </div>

      {error && <div class="err">Błąd: {error}</div>}

      <div class="addrow">
        <input
          class="grow"
          type="text"
          placeholder="co dokupić? (np. wata, rękawiczki S)"
          value={name}
          disabled={busy}
          onInput={(e) => setName((e.target as HTMLInputElement).value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
        />
        <button class="btn primary" disabled={busy} onClick={add}>
          Dodaj
        </button>
      </div>

      <h3>Do kupienia ({toBuy.length})</h3>
      <ul class="list">
        {toBuy.map((i) => (
          <li key={i.id}>
            <button class="check" title="Oznacz jako kupione" onClick={() => setStatus(i, 'bought')}>
              ☐
            </button>
            <span class="nm">{i.name}</span>
            {i.created_by && <span class="by">· {i.created_by}</span>}
            <button class="x" title="Usuń" onClick={() => remove(i.id)}>
              ×
            </button>
          </li>
        ))}
        {toBuy.length === 0 && <li class="muted small">Nic do kupienia 🎉</li>}
      </ul>

      {bought.length > 0 && (
        <>
          <h3>Kupione ({bought.length})</h3>
          <ul class="list done">
            {bought.map((i) => (
              <li key={i.id}>
                <button class="check" title="Przywróć do kupienia" onClick={() => setStatus(i, 'to_buy')}>
                  ☑
                </button>
                <span class="nm">{i.name}</span>
                <button class="x" title="Usuń" onClick={() => remove(i.id)}>
                  ×
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
