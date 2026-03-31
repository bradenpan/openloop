import { create } from "zustand";

type Theme = "dark" | "light";

interface UIState {
  // Navigation
  currentSpaceId: string | null;
  currentRoute: string;
  selectedItemId: string | null;

  // Layout
  sidebarCollapsed: boolean;
  odinExpanded: boolean;
  panelOpen: boolean;

  // Theme
  theme: Theme;

  // Actions
  setCurrentSpaceId: (id: string | null) => void;
  navigate: (route: string) => void;
  setSelectedItemId: (id: string | null) => void;
  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  setOdinExpanded: (expanded: boolean) => void;
  setPanelOpen: (open: boolean) => void;
  togglePanel: () => void;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

function getInitialTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  const stored = localStorage.getItem("openloop-theme");
  if (stored === "light" || stored === "dark") return stored;
  return "dark";
}

function applyTheme(theme: Theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("openloop-theme", theme);
}

const initialTheme = getInitialTheme();
applyTheme(initialTheme);

export const useUIStore = create<UIState>((set) => ({
  currentSpaceId: null,
  currentRoute: "/",
  selectedItemId: null,
  sidebarCollapsed: false,
  odinExpanded: false,
  panelOpen: false,
  theme: initialTheme,

  setCurrentSpaceId: (id) => set({ currentSpaceId: id }),
  navigate: (route) => {
    window.history.pushState(null, "", route);
    set({ currentRoute: route });
  },
  setSelectedItemId: (id) => set({ selectedItemId: id }),
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),
  setOdinExpanded: (expanded) => set({ odinExpanded: expanded }),
  setPanelOpen: (open) => set({ panelOpen: open }),
  togglePanel: () => set((s) => ({ panelOpen: !s.panelOpen })),
  setTheme: (theme) => {
    applyTheme(theme);
    set({ theme });
  },
  toggleTheme: () =>
    set((s) => {
      const next = s.theme === "dark" ? "light" : "dark";
      applyTheme(next);
      return { theme: next };
    }),
}));
