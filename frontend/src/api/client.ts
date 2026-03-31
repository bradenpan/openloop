import createFetchClient from 'openapi-fetch';
import type { paths } from './types';

export const api = createFetchClient<paths>({
  baseUrl: '', // Vite proxy handles /api → localhost:8010
});
