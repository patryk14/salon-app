// Beauty Plan editor (F10) — the printed booklet, digitised: skin type, morning /
// evening routine (four steps each), extra care, lifestyle, recommendations, and
// the treatment plan as steps with a done/planned counter. Written FOR the client:
// everything here is what she reads in her portal.
import { useEffect, useState } from 'preact/hooks';
import { apiFetch } from '../lib/api';

interface Step {
  id: number;
  treatment: string;
  sessions_planned: number;
  sessions_done: number;
  interval_note: string | null;
  note: string | null;
}
type TextKey =
  | 'skin_type'
  | 'am_cleansing'
  | 'am_antioxidant'
  | 'am_hydration'
  | 'am_spf'
  | 'pm_cleansing'
  | 'pm_therapeutic'
  | 'pm_serum'
  | 'pm_cream'
  | 'extra_care'
  | 'lifestyle'
  | 'recommendations';
type Plan = { id: number; status: string; updated_at: string; steps: Step[] } & Record<TextKey, string | null>;

const ROUTINE: [TextKey, string, TextKey, string][] = [
  ['am_cleansing', 'Oczyszczanie', 'pm_cleansing', 'Oczyszczanie'],
  ['am_antioxidant', 'Antyoksydacja', 'pm_therapeutic', 'Działanie terapeutyczne'],
  ['am_hydration', 'Nawilżenie', 'pm_serum', 'Serum'],
  ['am_spf', 'Krem z filtrem SPF', 'pm_cream', 'Krem pielęgnacyjny'],
];
const SECTIONS: [TextKey, string][] = [
  ['extra_care', 'Pielęgnacja dodatkowa'],
  ['lifestyle', 'Suplementacja, styl życia'],
  ['recommendations', 'Dodatkowe zalecenia'],
];
const ALL_KEYS: TextKey[] = ['skin_type', ...ROUTINE.flatMap((r) => [r[0], r[2]]), ...SECTIONS.map((s) => s[0])];
const emptyForm = () => Object.fromEntries(ALL_KEYS.map((k) => [k, ''])) as Record<TextKey, string>;

export default function BeautyPlanEditor({ clientId, services }: { clientId: number; services: string[] }) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [form, setForm] = useState(emptyForm());
  const [dirty, setDirty] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState({ treatment: '', sessions_planned: '1', interval_note: '' });

  function adopt(p: Plan | null) {
    setPlan(p);
    setForm(p ? (Object.fromEntries(ALL_KEYS.map((k) => [k, p[k] ?? ''])) as Record<TextKey, string>) : emptyForm());
    setDirty(false);
  }

  async function load() {
    try {
      adopt(await apiFetch<Plan | null>(`/clients/${clientId}/beauty-plan`));
      setLoaded(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  useEffect(() => {
    setLoaded(false);
    load();
  }, [clientId]);

  async function run(job: () => Promise<unknown>) {
    setError(null);
    try {
      await job();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const save = () =>
    run(async () =>
      adopt(await apiFetch<Plan>(`/clients/${clientId}/beauty-plan`, { method: 'PUT', body: JSON.stringify(form) })),
    );

  const addStep = () =>
    run(async () => {
      if (!step.treatment.trim()) return;
      // a step needs a plan to hang on — create it from the current form first
      let p = plan;
      if (!p) {
        p = await apiFetch<Plan>(`/clients/${clientId}/beauty-plan`, { method: 'PUT', body: JSON.stringify(form) });
        setDirty(false); // the PUT just saved the text sections too
      }
      await apiFetch(`/beauty-plans/${p.id}/steps`, {
        method: 'POST',
        body: JSON.stringify({
          treatment: step.treatment.trim(),
          sessions_planned: Math.max(1, Number(step.sessions_planned) || 1),
          interval_note: step.interval_note.trim() || null,
        }),
      });
      setStep({ treatment: '', sessions_planned: '1', interval_note: '' });
      const fresh = await apiFetch<Plan | null>(`/clients/${clientId}/beauty-plan`);
      // keep unsaved text edits; only the steps changed server-side
      setPlan(fresh);
    });

  const patchStep = (s: Step, body: Record<string, unknown>) =>
    run(async () => {
      const updated = await apiFetch<Step>(`/beauty-plan-steps/${s.id}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      });
      setPlan((p) => (p ? { ...p, steps: p.steps.map((x) => (x.id === s.id ? updated : x)) } : p));
    });

  const removeStep = (s: Step) =>
    run(async () => {
      await apiFetch(`/beauty-plan-steps/${s.id}`, { method: 'DELETE' });
      setPlan((p) => (p ? { ...p, steps: p.steps.filter((x) => x.id !== s.id) } : p));
    });

  const archive = () =>
    run(async () => {
      if (!confirm('Zamknąć ten plan i zacząć nowy? Stary zostanie w archiwum, klientka zobaczy nowy.')) return;
      await apiFetch(`/clients/${clientId}/beauty-plan/archive`, { method: 'POST' });
      adopt(null);
    });

  const field = (key: TextKey, label: string, rows = 2) => (
    <label class="fld">
      <span class="lbl">{label}</span>
      <textarea
        rows={rows}
        value={form[key]}
        onInput={(e) => {
          setForm({ ...form, [key]: (e.target as HTMLTextAreaElement).value });
          setDirty(true);
        }}
      />
    </label>
  );

  if (!loaded) return <p class="muted">{error ?? 'Ładowanie…'}</p>;

  return (
    <div>
      {error && <div class="err">{error}</div>}
      <p class="muted small">
        {plan
          ? `Plan aktywny · ostatnia zmiana ${plan.updated_at.slice(0, 10)}. Klientka widzi go w swoim profilu.`
          : 'Klientka nie ma jeszcze planu — wypełnij i zapisz. Zobaczy go w swoim profilu.'}
      </p>

      <div class="card">{field('skin_type', 'Typ skóry')}</div>

      <h2 class="section">Plan pielęgnacyjny</h2>
      <div class="routine">
        <div class="rhead">Pielęgnacja poranna</div>
        <div class="rhead">Pielęgnacja wieczorna</div>
        {ROUTINE.map(([am, amLabel, pm, pmLabel]) => [
          <div class="card" key={am}>
            {field(am, amLabel)}
          </div>,
          <div class="card" key={pm}>
            {field(pm, pmLabel)}
          </div>,
        ])}
      </div>

      {SECTIONS.map(([key, label]) => (
        <div class="card" key={key}>
          {field(key, label, 3)}
        </div>
      ))}

      <div class="bar">
        <button class="btn primary" disabled={!dirty} onClick={save}>
          {dirty ? 'Zapisz plan' : 'Zapisano'}
        </button>
        {plan && (
          <button class="btn" onClick={archive}>
            Zamknij i zacznij nowy
          </button>
        )}
      </div>

      <h2 class="section">Plan zabiegowy</h2>
      <div class="scroll">
        <table class="sessions">
          <thead>
            <tr>
              <th>Zabieg</th>
              <th>Odstęp</th>
              <th>Postęp</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(plan?.steps ?? []).map((s) => {
              const done = s.sessions_done >= s.sessions_planned;
              return (
                <tr key={s.id} class={done ? 'done' : ''}>
                  <td>{s.treatment}</td>
                  <td class="muted small">{s.interval_note ?? ''}</td>
                  <td class="nowrap">
                    <button
                      class="btn sm"
                      disabled={s.sessions_done <= 0}
                      onClick={() => patchStep(s, { sessions_done: s.sessions_done - 1 })}
                    >
                      −
                    </button>{' '}
                    <b>
                      {s.sessions_done} / {s.sessions_planned}
                    </b>{' '}
                    <button
                      class="btn sm"
                      disabled={s.sessions_done >= 99}
                      onClick={() => patchStep(s, { sessions_done: s.sessions_done + 1 })}
                    >
                      +
                    </button>
                    {done && <span class="badge ok"> ukończone</span>}
                  </td>
                  <td>
                    <button class="link danger" onClick={() => confirm('Usunąć ten krok?') && removeStep(s)}>
                      usuń
                    </button>
                  </td>
                </tr>
              );
            })}
            <tr class="add">
              <td>
                <input
                  list="bp-services"
                  placeholder="zabieg…"
                  value={step.treatment}
                  onInput={(e) => setStep({ ...step, treatment: (e.target as HTMLInputElement).value })}
                />
                <datalist id="bp-services">
                  {services.map((s) => (
                    <option key={s} value={s} />
                  ))}
                </datalist>
              </td>
              <td>
                <input
                  placeholder="np. co 3 tygodnie"
                  value={step.interval_note}
                  onInput={(e) => setStep({ ...step, interval_note: (e.target as HTMLInputElement).value })}
                />
              </td>
              <td>
                <input
                  class="num"
                  type="number"
                  min="1"
                  max="99"
                  title="Planowana liczba zabiegów"
                  value={step.sessions_planned}
                  onInput={(e) => setStep({ ...step, sessions_planned: (e.target as HTMLInputElement).value })}
                />{' '}
                <span class="muted small">zabiegów</span>
              </td>
              <td>
                <button class="btn primary sm" onClick={addStep}>
                  Dodaj
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
