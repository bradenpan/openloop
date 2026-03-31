import { useEffect, useRef, useCallback } from "react";
import { useSSEStore } from "@/stores/sse-store";
import { API_BASE } from "@/api/client";

const SSE_URL = `${API_BASE}/events`;
const MAX_RECONNECT_DELAY = 30_000;
const BASE_RECONNECT_DELAY = 1_000;

export function useSSE() {
  const sourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const status = useSSEStore((s) => s.status);
  const setStatus = useSSEStore((s) => s.setStatus);
  const setLastEvent = useSSEStore((s) => s.setLastEvent);
  const reconnectAttempts = useSSEStore((s) => s.reconnectAttempts);
  const incrementReconnectAttempts = useSSEStore((s) => s.incrementReconnectAttempts);
  const resetReconnectAttempts = useSSEStore((s) => s.resetReconnectAttempts);

  const connect = useCallback(() => {
    // Clean up existing connection
    if (sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
    }

    setStatus("connecting");

    const source = new EventSource(SSE_URL);
    sourceRef.current = source;

    source.onopen = () => {
      setStatus("connected");
      resetReconnectAttempts();
    };

    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data as string) as unknown;
        setLastEvent({
          type: (data as { type?: string }).type ?? "message",
          data,
          timestamp: Date.now(),
        });
      } catch {
        // non-JSON event, store raw
        setLastEvent({
          type: "raw",
          data: event.data,
          timestamp: Date.now(),
        });
      }
    };

    source.onerror = () => {
      source.close();
      sourceRef.current = null;
      setStatus("error");
      incrementReconnectAttempts();

      // Exponential backoff
      const delay = Math.min(
        BASE_RECONNECT_DELAY * Math.pow(2, reconnectAttempts),
        MAX_RECONNECT_DELAY
      );

      reconnectTimeoutRef.current = setTimeout(() => {
        connect();
      }, delay);
    };
  }, [setStatus, setLastEvent, resetReconnectAttempts, incrementReconnectAttempts, reconnectAttempts]);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
    }
    setStatus("disconnected");
  }, [setStatus]);

  useEffect(() => {
    connect();
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  return { status, connect, disconnect };
}
