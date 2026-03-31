import { create } from 'zustand';

export type PaletteId = 'slate-cyan' | 'warm-amber' | 'neutral-indigo';
export type ThemeId = 'dark' | 'light';

interface UIState {
  palette: PaletteId;
  theme: ThemeId;
  setPalette: (palette: PaletteId) => void;
  setTheme: (theme: ThemeId) => void;
  toggleTheme: () => void;

  sidebarCollapsed: boolean;
  odinExpanded: boolean;
  toggleSidebar: () => void;
  toggleOdin: () => void;

  currentSpaceId: string | null;
  selectedItemId: string | null;
  panelOpen: boolean;
  setCurrentSpace: (id: string | null) => void;
  setSelectedItem: (id: string | null) => void;
  togglePanel: () => void;
}

function applyToDOM(palette: PaletteId, theme: ThemeId) {
  document.documentElement.dataset.palette = palette;
  document.documentElement.dataset.theme = theme;
  localStorage.setItem('ol-palette', palette);
  localStorage.setItem('ol-theme', theme);
}

const savedPalette = (localStorage.getItem('ol-palette') as PaletteId) || 'slate-cyan';
const savedTheme = (localStorage.getItem('ol-theme') as ThemeId) || 'dark';
applyToDOM(savedPalette, savedTheme);

export const useUIStore = create<UIState>((set, get) => ({
  palette: savedPalette,
  theme: savedTheme,
  setPalette: (palette) => {
    set({ palette });
    applyToDOM(palette, get().theme);
  },
  setTheme: (theme) => {
    set({ theme });
    applyToDOM(get().palette, theme);
  },
  toggleTheme: () => {
    const next = get().theme === 'dark' ? 'light' : 'dark';
    set({ theme: next });
    applyToDOM(get().palette, next);
  },

  sidebarCollapsed: false,
  odinExpanded: false,
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  toggleOdin: () => set((s) => ({ odinExpanded: !s.odinExpanded })),

  currentSpaceId: null,
  selectedItemId: null,
  panelOpen: false,
  setCurrentSpace: (id) => set({ currentSpaceId: id }),
  setSelectedItem: (id) => set({ selectedItemId: id, panelOpen: id !== null }),
  togglePanel: () => set((s) => ({ panelOpen: !s.panelOpen })),
}));
