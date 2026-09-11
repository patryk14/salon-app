// Staff documents (Day 1, admin) — employment/RODO docs per employee with an
// expiry alert (< 30 days highlighted). Metadata only for now; scans arrive
// with the media slice (F9).
import { useEffect, useState } from 'preact/hooks';
import { getUser, groupsOf, login } from '../lib/auth';
import { apiFetch } from '../lib/api';

interface Employee {
  id: number;
  display_name: string;
  is_active: boolean;
}
interface Doc {
  id: number;
  employee_id: number;
  doc_type: string;
  title: string | null;
  valid_until: string | null;
  note: string | null;
}

function daysLeft(iso: string | null): number | null {
  if (!iso) return null;
  const ms = new Date(iso + 'T00:00:00').getTime() - Date.now();
  return Math.floor(ms / 86400000);
}

export default function StaffDocs() {
  const [ready, setReady] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [empId, setEmpId] = useState<number | ''>('');
  const [docType, setDocType] = useState('umowa');
  const [title, setTitle] = useState('');
  const [validUntil, setValidUntil] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      const user = await getUser();
      if (user && !user.expired) setIsAdmin(groupsOf(user).includes('admin'));
      setReady(true);
    })();
  }, []);

  async function load() {
    setError(null);
    try {
      const [emps, ds] = await Promise.all([
        apiFetch<Employee[]>('/employees'),
        apiFetch<Doc[]>('/staff-documents'),
      ]);
      setEmployees(emps.filter((e) => e.is_active));
      setDocs(ds);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (ready && isAdmin) load();
  }, [ready, isAdmin]);

  async function add() {
    if (!empId) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch('/staff-documents', {
        method: 'POST',
        body: JSON.stringify({
          employee_id: empId,
          doc_type: docType,
          title: title.trim() || null,
          valid_until: validUntil || null,
        }),
      });
      setTitle('');
      setValidUntil('');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: number) {
    try {
      await apiFetch(`/staff-documents/${id}`, { method: 'DELETE' });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const nameOf = (id: number) => employees.find((e) => e.id === id)?.display_name ?? `#${id}`;

  if (!ready) return <p class="muted">Ładowanie…</p>;
  if (!isAdmin) {
    return (
      <div class="gate">
        <h2>Dokumenty pracownic</h2>
        <p class="muted">Zaloguj się kontem właścicielki.</p>
        <button class="btn primary" onClick={() => login()}>
          Zaloguj przez Cognito
        </button>
      </div>
    );
  }

  return (
    <div>

      {error && <div class="err">Błąd: {error}</div>}

      <div class="addrow">
        <select value={empId} disabled={busy} onChange={(e) => setEmpId(Number((e.target as HTMLSelectElement).value) || '')}>
          <option value="">— pracownica —</option>
          {employees.map((e) => (
            <option value={e.id} key={e.id}>
              {e.display_name}
            </option>
          ))}
        </select>
        <select value={docType} disabled={busy} onChange={(e) => setDocType((e.target as HTMLSelectElement).value)}>
          <option value="umowa">umowa</option>
          <option value="rodo">RODO</option>
          <option value="inne">inne</option>
        </select>
        <input
          class="grow"
          type="text"
          placeholder="nazwa (opcjonalnie)"
          value={title}
          disabled={busy}
          onInput={(e) => setTitle((e.target as HTMLInputElement).value)}
        />
        <label class="dt">
          ważne do:{' '}
          <input type="date" value={validUntil} disabled={busy} onInput={(e) => setValidUntil((e.target as HTMLInputElement).value)} />
        </label>
        <button class="btn primary" disabled={busy || !empId} onClick={add}>
          Dodaj
        </button>
      </div>

      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>Pracownica</th>
              <th>Typ</th>
              <th>Nazwa</th>
              <th>Ważne do</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {docs.map((d) => {
              const dl = daysLeft(d.valid_until);
              const cls = dl === null ? '' : dl < 0 ? 'expired' : dl < 30 ? 'soon' : '';
              return (
                <tr key={d.id}>
                  <td>{nameOf(d.employee_id)}</td>
                  <td>{d.doc_type}</td>
                  <td>{d.title ?? '—'}</td>
                  <td class={cls}>
                    {d.valid_until ?? '—'}
                    {dl !== null && dl < 30 && (
                      <span class="tag">{dl < 0 ? 'wygasła' : `za ${dl} dni`}</span>
                    )}
                  </td>
                  <td>
                    <button class="x" title="Usuń" onClick={() => remove(d.id)}>
                      ×
                    </button>
                  </td>
                </tr>
              );
            })}
            {docs.length === 0 && (
              <tr>
                <td colSpan={5} class="muted" style="text-align:center;padding:1.5rem">
                  Brak dokumentów.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
