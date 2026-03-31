import { create } from "zustand";

type SSEConnectionStatus = "disconnected" | "connecting" | "connected" | "error";

interface SSEEvent {
  type: string;
  data: unknown;
  timestamp: number;
}

interface SSEState {
  status: SSEConnectionStatus;
  lastEvent: SSEEvent | null;
  reconnectAttempts: number;

  setStatus: (status: SSEConnectionStatus) => void;
  setLastEvent: (event: SSEEvent) => void;
  incrementReconnectAttempts: () => void;
  resetReconnectAttempts: () => void;
}

export const useSSEStore = create<SSEState>((set) => ({
  status: "disconnected",
  lastEvent: null,
  reconnectAttempts: 0,

  setStatus: (status) => set({ status }),
  setLastEvent: (event) => set({ lastEvent: event }),
  incrementReconnectAttempts: () =>
    set((s) => ({ reconnectAttempts: s.reconnectAttempts + 1 })),
  resetReconnectAttempts: () => set({ reconnectAttempts: 0 }),
}));
