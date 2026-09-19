// Thin API client: attach the bearer token, parse JSON, surface errors.
// The API is the authority — this never decides access, it just carries the
// token and reports what the API said.
import { PUBLIC_API_URL } from 'astro:env/client';
import { getAccessToken } from './auth';

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

// FastAPI reports validation problems (422) as a LIST of {loc, msg, type, ctx}.
// Turn it into one readable Polish line per field instead of "[object Object]".
const FIELD_PL: Record<string, string> = {
  first_name: 'Imię', last_name: 'Nazwisko', phone: 'Telefon', email: 'E-mail',
  session_date: 'Data', measured_on: 'Data', session_no: 'Zabieg nr', treatment: 'Zabieg',
  parameters: 'Parametry', preparation: 'Użyty preparat', notes: 'Uwagi',
  arms: 'Ramiona', belly: 'Brzuch', buttocks: 'Pośladki', thighs: 'Uda', calves: 'Łydki',
  weight: 'Waga', sessions_planned: 'Liczba zabiegów', sessions_done: 'Wykonane',
  amount_pln: 'Kwota', hours: 'Godziny',
};
interface ValidationItem {
  loc?: (string | number)[];
  msg?: string;
  type?: string;
  ctx?: Record<string, unknown>;
}
function describeValidation(item: ValidationItem): string {
  const key = String(item.loc?.[item.loc.length - 1] ?? '');
  const field = FIELD_PL[key] ?? key;
  const c = item.ctx ?? {};
  const why =
    {
      missing: 'pole wymagane',
      less_than_equal: `maksymalnie ${c.le}`,
      greater_than_equal: `minimalnie ${c.ge}`,
      less_than: `musi być mniejsze niż ${c.lt}`,
      greater_than: `musi być większe niż ${c.gt}`,
      decimal_max_places: `najwyżej ${c.decimal_places} miejsce po przecinku`,
      decimal_max_digits: `za dużo cyfr (najwyżej ${c.max_digits})`,
      decimal_parsing: 'to nie jest liczba',
      int_parsing: 'to nie jest liczba całkowita',
      string_too_long: `za długie (najwyżej ${c.max_length} znaków)`,
      string_too_short: 'pole nie może być puste',
      date_from_datetime_parsing: 'niepoprawna data',
      date_parsing: 'niepoprawna data',
    }[item.type ?? ''] ??
    item.msg ??
    'niepoprawna wartość';
  return field ? `${field}: ${why}` : why;
}
function errorDetail(body: unknown, fallback: string): string {
  if (!body || typeof body !== 'object' || !('detail' in body)) return fallback;
  const detail = (body as { detail: unknown }).detail;
  if (Array.isArray(detail)) return detail.map((d) => describeValidation(d as ValidationItem)).join(' · ');
  return typeof detail === 'string' ? detail : JSON.stringify(detail);
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getAccessToken();
  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  // JSON by default, but let the browser set the multipart boundary for uploads.
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const res = await fetch(`${PUBLIC_API_URL}${path}`, { ...init, headers });

  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;

  if (!res.ok) {
    throw new ApiError(res.status, errorDetail(body, res.statusText));
  }
  return body as T;
}

// Binary GET with the bearer token (progress photos). Photos are never exposed
// through a shareable URL — the bytes come only to an authenticated caller.
export async function apiFetchBlob(path: string): Promise<Blob> {
  const token = await getAccessToken();
  const headers = new Headers();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const res = await fetch(`${PUBLIC_API_URL}${path}`, { headers });
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  return res.blob();
}
