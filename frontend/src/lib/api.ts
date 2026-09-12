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
    const detail =
      body && typeof body === 'object' && 'detail' in body ? String(body.detail) : res.statusText;
    throw new ApiError(res.status, detail);
  }
  return body as T;
}
