import { useEffect, useRef } from 'react';
import { create } from 'zustand';

export interface SSETokenEvent {
  type: 'token';
  conversation_id: string;
  content: string;
}

export interface SSEToolCallEvent {
  type: 'tool_call';
  conversation_id: string;
  tool_name: string;
  status: 'started' | 'completed' | 'failed';
}

export interface SSEToolResultEvent {
  type: 'tool_result';
  conversation_id: string;
  tool_name: string;
  result_summary: string;
}

export interface SSEApprovalRequestEvent {
  type: 'approval_request';
  conversation_id: string;
  request_id: string;
  tool_name: string;
  resource: string;
  operation: string;
}

export interface SSENotificationEvent {
  type: 'notification';
  notification_id: string;
  notification_type: string;
  title: string;
  body: string | null;
}

export interface SSERouteEvent {
  type: 'route';
  space_id: string | null;
  conversation_id: string | null;
}

export interface SSEBackgroundUpdateEvent {
  type: 'background_update';
  task_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress: number | null;
}

export interface SSEBackgroundProgressEvent {
  type: 'background_progress';
  conversation_id: string;
  task_id: string;
  turn: number;
  completed: boolean;
  summary: string;
}

export interface SSEErrorEvent {
  type: 'error';
  conversation_id: string | null;
  message: string;
}

export type SSEEvent =
  | SSETokenEvent
  | SSEToolCallEvent
  | SSEToolResultEvent
  | SSEApprovalRequestEvent
  | SSENotificationEvent
  | SSERouteEvent
  | SSEBackgroundUpdateEvent
  | SSEBackgroundProgressEvent
  | SSEErrorEvent;

export type SSEStatus = 'connecting' | 'connected' | 'disconnected' | 'error';
type SSEHandler = (event: SSEEvent) => void;

interface SSEState {
  status: SSEStatus;
  handlers: Set<SSEHandler>;
  subscribe: (handler: SSEHandler) => () => void;
}

export const useSSEStore = create<SSEState>((set) => ({
  status: 'disconnected',
  handlers: new Set(),
  subscribe: (handler) => {
    set((state) => ({ handlers: new Set([...state.handlers, handler]) }));
    return () => {
      set((state) => {
        const updated = new Set(state.handlers);
        updated.delete(handler);
        return { handlers: updated };
      });
    };
  },
}));

const SSE_URL = '/api/v1/events';
const MAX_RETRY_DELAY = 30_000;
const BASE_RETRY_DELAY = 1_000;

const EVENT_TYPES = [
  'token', 'tool_call', 'tool_result', 'approval_request',
  'notification', 'route', 'background_update', 'background_progress', 'error',
];

function dispatch(event: SSEEvent) {
  useSSEStore.getState().handlers.forEach((h) => h(event));
}

export function useSSEConnection() {
  const esRef = useRef<EventSource | null>(null);
  const retryCount = useRef(0);
  const retryTimer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    function connect() {
      useSSEStore.setState({ status: 'connecting' });
      const es = new EventSource(SSE_URL);
      esRef.current = es;

      es.onopen = () => {
        retryCount.current = 0;
        useSSEStore.setState({ status: 'connected' });
      };

      for (const type of EVENT_TYPES) {
        es.addEventListener(type, (e) => {
          try {
            const data = JSON.parse((e as MessageEvent).data);
            dispatch({ ...data, type });
          } catch { /* ignore malformed */ }
        });
      }

      es.onerror = () => {
        es.close();
        useSSEStore.setState({ status: 'error' });
        const delay = Math.min(BASE_RETRY_DELAY * 2 ** retryCount.current, MAX_RETRY_DELAY);
        retryCount.current++;
        retryTimer.current = setTimeout(connect, delay);
      };
    }

    connect();

    return () => {
      esRef.current?.close();
      if (retryTimer.current) clearTimeout(retryTimer.current);
      useSSEStore.setState({ status: 'disconnected' });
    };
  }, []);

  return useSSEStore((s) => s.status);
}

export function useSSEEvent(handler: SSEHandler) {
  const ref = useRef(handler);
  ref.current = handler;

  useEffect(() => {
    return useSSEStore.getState().subscribe((event) => ref.current(event));
  }, []);
}
