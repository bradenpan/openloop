import createClient from 'openapi-react-query';
import { api } from './client';

export const $api = createClient(api);
