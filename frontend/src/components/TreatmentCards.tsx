// Treatment cards (F10) — the salon's internal working record for one client:
// a card per treatment type with its session log (and body measurements for
// endermologia). Mirrors the paper cards; holds NO health data — the signed paper
// stays the legal record, here we only note that it was signed and checked.
import { useEffect, useState } from 'preact/hooks';
import { apiFetch } from '../lib/api';

interface CardType {
  id: number;
  code: string;
  name: string;
  session_variant: 'parameters' | 'preparation' | 'laser';
  has_measurements: boolean;
  aftercare: string | null;
  active: boolean;
}
interface Session {
  id: number;
  visit_id: number | null;
  session_date: string;
  treatment: string | null;
  parameters: string | null;
  preparation: string | null;
  notes: string | null;
  performed_by_sub: string | null;
  performed_by_name: string | null;
}
interface Measurement {
  id: number;
  measured_on: string;
  session_no: number | null;
  arms: string | null;
  belly: string | null;
  buttocks: string | null;
  thighs: string | null;
  calves: string | null;
  weight: string | null;
  notes: string | null;
}
interface Card {
  id: number;
  card_type: CardType;
  paper_signed_on: string | null;
  contraindications_checked: boolean;
  note: string | null;
  sessions: Session[];
  measurements: Measurement[];
}
interface Visit {
  id: number;
  starts_at: string;
  service_name: string;
}

const today = () => new Date().toISOString().slice(0, 10);
const MEASURES: [keyof Measurement, string][] = [
  ['arms', 'Ramiona'],
  ['belly', 'Brzuch'],
  ['buttocks', 'Pośladki'],
  ['thighs', 'Uda'],
  ['calves', 'Łydki'],
  ['weight', 'Waga'],
];
// Column set per paper-card variant.
const COLS: Record<CardType['session_variant'], [keyof Session, string][]> = {
  parameters: [
    ['treatment', 'Zabieg'],
    ['parameters', 'Parametry'],
  ],
  preparation: [
    ['preparation', 'Użyty preparat'],
    ['notes', 'Uwagi'],
  ],
  laser: [
    ['treatment', 'Typ zabiegu laserowego'],
    ['parameters', 'Parametry'],
    ['notes', 'Uwagi'],
  ],
};

export default function TreatmentCards(props: {
  clientId: number;
  visits: Visit[];
  isAdmin: boolean;
  mySub: string | null;
}) {
  const { clientId, visits, isAdmin, mySub } = props;
  const [types, setTypes] = useState<CardType[]>([]);
  const [cards, setCards] = useState<Card[]>([]);
  const [openId, setOpenId] = useState<number | null>(null);
  const [newType, setNewType] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({ session_date: today() });
  const [mDraft, setMDraft] = useState<Record<string, string>>({ measured_on: today() });

  async function load() {
    try {
      const [t, c] = await Promise.all([
        apiFetch<CardType[]>('/card-types'),
        apiFetch<Card[]>(`/clients/${clientId}/cards`),
      ]);
      setTypes(t);
      setCards(c);
      setOpenId((cur) => cur ?? c[0]?.id ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  useEffect(() => {
    setOpenId(null);
    load();
  }, [clientId]);

  async function run(job: () => Promise<unknown>) {
    setError(null);
    try {
      await job();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const openCard = () =>
    run(async () => {
      if (!newType) return;
      const card = await apiFetch<Card>(`/clients/${clientId}/cards`, {
        method: 'POST',
        body: JSON.stringify({ card_type_id: Number(newType) }),
      });
      setNewType('');
      setOpenId(card.id);
    });

  const patchCard = (id: number, body: Record<string, unknown>) =>
    run(() => apiFetch(`/cards/${id}`, { method: 'PATCH', body: JSON.stringify(body) }));

  const addSession = (card: Card) =>
    run(async () => {
      const body: Record<string, unknown> = { session_date: draft.session_date || today() };
      for (const [key] of COLS[card.card_type.session_variant]) body[key] = draft[key]?.trim() || null;
      if (draft.visit_id) body.visit_id = Number(draft.visit_id);
      await apiFetch(`/cards/${card.id}/sessions`, { method: 'POST', body: JSON.stringify(body) });
      setDraft({ session_date: today() });
    });

  const addMeasurement = (card: Card) =>
    run(async () => {
      const body: Record<string, unknown> = { measured_on: mDraft.measured_on || today() };
      if (mDraft.session_no) body.session_no = Number(mDraft.session_no);
      for (const [key] of MEASURES) {
        const v = mDraft[key as string]?.replace(',', '.').trim();
        if (v) body[key as string] = v;
      }
      if (mDraft.notes?.trim()) body.notes = mDraft.notes.trim();
      await apiFetch(`/cards/${card.id}/measurements`, { method: 'POST', body: JSON.stringify(body) });
      setMDraft({ measured_on: today() });
    });

  const taken = new Set(cards.map((c) => c.card_type.id));
  const available = types.filter((t) => t.active && !taken.has(t.id));
  const card = cards.find((c) => c.id === openId) ?? null;
  const cols = card ? COLS[card.card_type.session_variant] : [];

  return (
    <div>
      {error && <div class="err">{error}</div>}
      <p class="muted small">
        Karta jest wewnętrzna — klientka jej nie widzi. Nie wpisuj tu danych o zdrowiu: przeciwwskazania,
        wywiad i podpisy zostają na karcie papierowej.
      </p>

      <div class="bar">
        {cards.map((c) => (
          <button class={`chip${c.id === openId ? ' active' : ''}`} key={c.id} onClick={() => setOpenId(c.id)}>
            {c.card_type.name} <span class="muted">({c.sessions.length})</span>
          </button>
        ))}
        {available.length > 0 && (
          <span class="inline">
            <select value={newType} onChange={(e) => setNewType((e.target as HTMLSelectElement).value)}>
              <option value="">+ załóż kartę…</option>
              {available.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
            {newType && (
              <button class="btn sm primary" onClick={openCard}>
                Załóż
              </button>
            )}
          </span>
        )}
      </div>

      {!card && <p class="muted">Brak kart — załóż pierwszą z listy powyżej.</p>}
      {card && (
        <div>
          <div class="card paper">
            <label class="fld">
              <span class="lbl">Karta papierowa podpisana dnia</span>
              <input
                type="date"
                value={card.paper_signed_on ?? ''}
                onChange={(e) =>
                  patchCard(card.id, { paper_signed_on: (e.target as HTMLInputElement).value || null })
                }
              />
            </label>
            <label class="chk">
              <input
                type="checkbox"
                checked={card.contraindications_checked}
                onChange={(e) =>
                  patchCard(card.id, { contraindications_checked: (e.target as HTMLInputElement).checked })
                }
              />
              przeciwwskazania zweryfikowane (na papierze)
            </label>
            {!card.paper_signed_on && <span class="badge warn">brak podpisanej karty</span>}
          </div>

          <div class="scroll">
            <table class="sessions">
              <thead>
                <tr>
                  <th>Data</th>
                  {cols.map(([, label]) => (
                    <th key={label}>{label}</th>
                  ))}
                  <th>Wykonała</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                <tr class="add">
                  <td>
                    <input
                      type="date"
                      value={draft.session_date ?? ''}
                      onInput={(e) => setDraft({ ...draft, session_date: (e.target as HTMLInputElement).value })}
                    />
                    <select
                      title="Powiąż z wizytą (opcjonalnie)"
                      value={draft.visit_id ?? ''}
                      onChange={(e) => {
                        const id = (e.target as HTMLSelectElement).value;
                        const v = visits.find((x) => String(x.id) === id);
                        setDraft({
                          ...draft,
                          visit_id: id,
                          ...(v ? { session_date: v.starts_at.slice(0, 10) } : {}),
                        });
                      }}
                    >
                      <option value="">bez wizyty</option>
                      {visits.map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.starts_at.slice(0, 10)} · {v.service_name}
                        </option>
                      ))}
                    </select>
                  </td>
                  {cols.map(([key, label]) => (
                    <td key={key}>
                      <textarea
                        rows={2}
                        placeholder={label}
                        value={draft[key] ?? ''}
                        onInput={(e) => setDraft({ ...draft, [key]: (e.target as HTMLTextAreaElement).value })}
                      />
                    </td>
                  ))}
                  <td colSpan={2}>
                    <button class="btn primary sm" onClick={() => addSession(card)}>
                      Dodaj sesję
                    </button>
                  </td>
                </tr>
                {card.sessions.map((s, i) => (
                  <tr key={s.id}>
                    <td class="nowrap">
                      {s.session_date}
                      <div class="muted small">sesja {card.sessions.length - i}</div>
                    </td>
                    {cols.map(([key]) => (
                      <td key={key} class="pre">
                        {(s[key] as string | null) ?? '—'}
                      </td>
                    ))}
                    <td class="muted small">{s.performed_by_name ?? '—'}</td>
                    <td>
                      {(isAdmin || s.performed_by_sub === mySub) && (
                        <button
                          class="link danger"
                          onClick={() =>
                            confirm('Usunąć tę sesję z karty?') &&
                            run(() => apiFetch(`/card-sessions/${s.id}`, { method: 'DELETE' }))
                          }
                        >
                          usuń
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {card.card_type.has_measurements && (
            <div>
              <h2 class="section">Pomiary ciała (cm / kg)</h2>
              <div class="scroll">
                <table class="sessions measure">
                  <thead>
                    <tr>
                      <th>Data</th>
                      <th>Zabieg nr</th>
                      {MEASURES.map(([, label]) => (
                        <th key={label} class="amt">
                          {label}
                        </th>
                      ))}
                      <th>Uwagi</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {card.measurements.map((m) => (
                      <tr key={m.id}>
                        <td class="nowrap">{m.measured_on}</td>
                        <td>{m.session_no ?? '—'}</td>
                        {MEASURES.map(([key]) => (
                          <td key={key as string} class="amt">
                            {(m[key] as string | null) ?? '—'}
                          </td>
                        ))}
                        <td class="small">{m.notes ?? ''}</td>
                        <td>
                          <button
                            class="link danger"
                            onClick={() =>
                              confirm('Usunąć ten pomiar?') &&
                              run(() => apiFetch(`/card-measurements/${m.id}`, { method: 'DELETE' }))
                            }
                          >
                            usuń
                          </button>
                        </td>
                      </tr>
                    ))}
                    <tr class="add">
                      <td>
                        <input
                          type="date"
                          value={mDraft.measured_on ?? ''}
                          onInput={(e) => setMDraft({ ...mDraft, measured_on: (e.target as HTMLInputElement).value })}
                        />
                      </td>
                      <td>
                        <input
                          class="num"
                          type="number"
                          min="0"
                          placeholder="5"
                          value={mDraft.session_no ?? ''}
                          onInput={(e) => setMDraft({ ...mDraft, session_no: (e.target as HTMLInputElement).value })}
                        />
                      </td>
                      {MEASURES.map(([key]) => (
                        <td key={key as string}>
                          <input
                            class="num"
                            inputMode="decimal"
                            placeholder={key === 'weight' ? 'kg' : 'cm'}
                            title="0–999, najwyżej jedno miejsce po przecinku"
                            value={mDraft[key as string] ?? ''}
                            onInput={(e) =>
                              setMDraft({ ...mDraft, [key as string]: (e.target as HTMLInputElement).value })
                            }
                          />
                        </td>
                      ))}
                      <td>
                        <input
                          value={mDraft.notes ?? ''}
                          onInput={(e) => setMDraft({ ...mDraft, notes: (e.target as HTMLInputElement).value })}
                        />
                      </td>
                      <td>
                        <button class="btn primary sm" onClick={() => addMeasurement(card)}>
                          Dodaj
                        </button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {card.card_type.aftercare && (
            <details class="card">
              <summary>Zalecenia pozabiegowe (widzi je klientka w swoim profilu)</summary>
              <ul class="after">
                {card.card_type.aftercare.split('\n').map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
