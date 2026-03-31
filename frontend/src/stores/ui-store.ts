import { create } from 'zustand'

interface UIState {
  currentSpaceId: string | null
  selectedItemId: string | null
  panelOpen: boolean
  setCurrentSpace: (id: string | null) => void
  setSelectedItem: (id: string | null) => void
  togglePanel: () => void
}

export const useUIStore = create<UIState>((set) => ({
  currentSpaceId: null,
  selectedItemId: null,
  panelOpen: false,
  setCurrentSpace: (id) => set({ currentSpaceId: id }),
  setSelectedItem: (id) => set({ selectedItemId: id }),
  togglePanel: () => set((s) => ({ panelOpen: !s.panelOpen })),
}))
