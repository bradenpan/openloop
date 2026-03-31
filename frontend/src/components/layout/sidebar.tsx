import { useUIStore } from "@/stores/ui-store";
import { Badge } from "@/components/ui";

interface SpaceStub {
  id: string;
  name: string;
  template: string;
  status: "active" | "idle" | "error";
}

const PLACEHOLDER_SPACES: SpaceStub[] = [
  { id: "1", name: "Job Search", template: "project", status: "active" },
  { id: "2", name: "Marketing", template: "area", status: "idle" },
  { id: "3", name: "Side Project", template: "project", status: "active" },
  { id: "4", name: "Reading List", template: "resource", status: "idle" },
  { id: "5", name: "Finances", template: "area", status: "error" },
];

const statusColor: Record<SpaceStub["status"], string> = {
  active: "bg-[var(--color-success)]",
  idle: "bg-[var(--color-text-tertiary)]",
  error: "bg-[var(--color-danger)]",
};

function Sidebar() {
  const sidebarCollapsed = useUIStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const currentSpaceId = useUIStore((s) => s.currentSpaceId);
  const setCurrentSpaceId = useUIStore((s) => s.setCurrentSpaceId);
  const navigate = useUIStore((s) => s.navigate);

  return (
    <aside
      className={[
        "h-screen shrink-0 flex flex-col",
        "bg-[var(--color-bg-secondary)] border-r border-[var(--color-border-default)]",
        "transition-[width] duration-[var(--transition-normal)]",
        "overflow-hidden",
      ].join(" ")}
      style={{
        width: sidebarCollapsed
          ? "var(--sidebar-width-collapsed)"
          : "var(--sidebar-width)",
      }}
    >
      {/* Top: Logo + toggle */}
      <div className="flex items-center justify-between px-3 h-12 shrink-0 border-b border-[var(--color-border-subtle)]">
        {!sidebarCollapsed && (
          <button
            onClick={() => navigate("/")}
            className="flex items-center gap-2 cursor-pointer group"
          >
            <div className="w-5 h-5 rounded-[var(--radius-sm)] bg-[var(--color-accent)] flex items-center justify-center">
              <span className="text-[10px] font-bold text-[var(--color-text-inverse)]">O</span>
            </div>
            <span className="text-[var(--text-sm)] font-semibold text-[var(--color-text-primary)] group-hover:text-[var(--color-accent-text)] transition-colors">
              OpenLoop
            </span>
          </button>
        )}
        <button
          onClick={toggleSidebar}
          className="p-1.5 rounded-[var(--radius-sm)] text-[var(--color-text-tertiary)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-bg-hover)] transition-colors cursor-pointer"
          aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path
              d="M3 4h10M3 8h10M3 12h10"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
        </button>
      </div>

      {/* Home link */}
      {!sidebarCollapsed && (
        <div className="px-2 py-2">
          <button
            onClick={() => {
              setCurrentSpaceId(null);
              navigate("/");
            }}
            className={[
              "w-full flex items-center gap-2 px-2 py-1.5 rounded-[var(--radius-sm)]",
              "text-[var(--text-sm)] transition-colors cursor-pointer",
              currentSpaceId === null
                ? "bg-[var(--color-bg-hover)] text-[var(--color-text-primary)]"
                : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)]",
            ].join(" ")}
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <path
                d="M2 8l6-5.5L14 8M4 7v6h3v-3h2v3h3V7"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            Home
          </button>
        </div>
      )}

      {/* Spaces list */}
      {!sidebarCollapsed && (
        <div className="flex-1 overflow-y-auto px-2 py-1">
          <div className="flex items-center justify-between px-2 py-1 mb-1">
            <span className="text-[var(--text-xs)] font-medium text-[var(--color-text-tertiary)] uppercase tracking-wider">
              Spaces
            </span>
            <Badge variant="default">{PLACEHOLDER_SPACES.length}</Badge>
          </div>
          <nav className="flex flex-col gap-0.5">
            {PLACEHOLDER_SPACES.map((space) => (
              <button
                key={space.id}
                onClick={() => {
                  setCurrentSpaceId(space.id);
                  navigate(`/spaces/${space.id}`);
                }}
                className={[
                  "w-full flex items-center gap-2 px-2 py-1.5 rounded-[var(--radius-sm)]",
                  "text-[var(--text-sm)] text-left transition-colors cursor-pointer",
                  currentSpaceId === space.id
                    ? "bg-[var(--color-bg-hover)] text-[var(--color-text-primary)]"
                    : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)]",
                ].join(" ")}
              >
                <span
                  className={[
                    "w-1.5 h-1.5 rounded-full shrink-0",
                    statusColor[space.status],
                  ].join(" ")}
                />
                <span className="truncate">{space.name}</span>
              </button>
            ))}
          </nav>
        </div>
      )}

      {/* Collapsed state: just status dots */}
      {sidebarCollapsed && (
        <div className="flex-1 overflow-y-auto flex flex-col items-center gap-1 py-2">
          <button
            onClick={() => {
              setCurrentSpaceId(null);
              navigate("/");
            }}
            className="p-2 rounded-[var(--radius-sm)] text-[var(--color-text-tertiary)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-bg-hover)] transition-colors cursor-pointer"
            title="Home"
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <path
                d="M2 8l6-5.5L14 8M4 7v6h3v-3h2v3h3V7"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
          {PLACEHOLDER_SPACES.map((space) => (
            <button
              key={space.id}
              onClick={() => {
                setCurrentSpaceId(space.id);
                navigate(`/spaces/${space.id}`);
              }}
              className={[
                "p-2 rounded-[var(--radius-sm)] transition-colors cursor-pointer",
                currentSpaceId === space.id
                  ? "bg-[var(--color-bg-hover)]"
                  : "hover:bg-[var(--color-bg-hover)]",
              ].join(" ")}
              title={space.name}
            >
              <span
                className={[
                  "block w-2 h-2 rounded-full",
                  statusColor[space.status],
                ].join(" ")}
              />
            </button>
          ))}
        </div>
      )}

      {/* Bottom: Settings */}
      <div className="px-2 py-2 border-t border-[var(--color-border-subtle)] shrink-0">
        <button
          onClick={() => navigate("/settings")}
          className={[
            "flex items-center gap-2 px-2 py-1.5 rounded-[var(--radius-sm)]",
            "text-[var(--text-sm)] text-[var(--color-text-tertiary)]",
            "hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)]",
            "transition-colors cursor-pointer",
            sidebarCollapsed ? "w-full justify-center" : "w-full",
          ].join(" ")}
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
            <circle cx="8" cy="8" r="2" stroke="currentColor" strokeWidth="1.5" />
            <path
              d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.05 3.05l1.06 1.06M11.89 11.89l1.06 1.06M3.05 12.95l1.06-1.06M11.89 4.11l1.06-1.06"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
          {!sidebarCollapsed && <span>Settings</span>}
        </button>
      </div>
    </aside>
  );
}

export { Sidebar };
