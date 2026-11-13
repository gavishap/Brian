import createClient, { type Middleware } from 'openapi-fetch';

import { config } from '@/lib/config';
import { getAccessToken } from '@/lib/supabase';

import type { paths } from './schema';

const auth: Middleware = {
  async onRequest({ request }) {
    const token = await getAccessToken();
    if (token) {
      request.headers.set('Authorization', `Bearer ${token}`);
    }
    return request;
  },
};

/** Typed client for the Brian API, generated from services/api/openapi.json (`npm run gen:api`). */
export const api = createClient<paths>({ baseUrl: config.apiUrl });
api.use(auth);

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(ApiError.describe(status, detail));
    this.name = 'ApiError';
  }

  static describe(status: number, detail: unknown): string {
    if (detail && typeof detail === 'object' && 'detail' in detail) {
      const inner = (detail as { detail: unknown }).detail;
      if (typeof inner === 'string') return inner;
    }
    if (status === 0) return 'Network error. Check your connection.';
    return `Request failed (${status})`;
  }
}

type Result<T> = { data?: T; error?: unknown; response: Response };

/** Return `data` or throw an ApiError (TanStack Query surfaces it as the query/mutation error). */
export function unwrap<T>(result: Result<T>): T {
  if (result.error !== undefined || !result.response.ok) {
    throw new ApiError(result.response.status, result.error);
  }
  return result.data as T;
}
