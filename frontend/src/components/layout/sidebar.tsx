import { useState } from 'react';
import { NavLink } from 'react-router-dom';
import { useUIStore } from '../../stores/ui-store';
import { $api } from '../../api/hooks';
import { SearchButton } from '../search-modal';
import { CreateSpaceModal } from '../home/create-space-modal';

function EmailIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="shrink-0"
    >
      <rect x="2" y="4" width="20" height="16" rx="2" ry="2" />
      <polyline points="22,6 12,13 2,6" />
    </svg>
  );
}

function CalendarIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="shrink-0"
    >
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
      <line x1="16" y1="2" x2="16" y2="6" />
      <line x1="8" y1="2" x2="8" y2="6" />
      <line x1="3" y1="10" x2="21" y2="10" />
    </svg>
  );
}

export function Sidebar() {
  const collapsed = useUIStore((s) => s.sidebarCollapsed);
  const toggle = useUIStore((s) => s.toggleSidebar);
  const { data } = $api.useQuery('get', '/api/v1/spaces', { params: { query: { limit: 50 } } });
  const calendarAuth = $api.useQuery('get', '/api/v1/calendar/auth-status');
  const calendarConnected = calendarAuth.data?.authenticated === true;
  const emailAuth = $api.useQuery('get', '/api/v1/email/auth-status');
  const emailConnected = emailAuth.data?.authenticated === true;
  const [createModalOpen, setCreateModalOpen] = useState(false);

  if (collapsed) {
    return (
      <aside className="w-12 h-full bg-surface border-r border-border flex flex-col items-center py-3 shrink-0">
        <button
          onClick={toggle}
          className="p-2 rounded-md text-muted hover:text-foreground hover:bg-raised transition-colors cursor-pointer"
          aria-label="Open sidebar"
        >
          &#9776;
        </button>
        <SearchButton collapsed />
      </aside>
    );
  }

  const spaces = data ?? [];

  return (
    <aside className="w-60 h-full bg-surface border-r border-border flex flex-col shrink-0">
      <div className="px-4 py-3 flex items-center justify-between border-b border-border">
        <span className="text-sm font-bold text-foreground tracking-wide">OpenLoop</span>
        <button
          onClick={toggle}
          className="text-muted hover:text-foreground transition-colors p-1 rounded-md hover:bg-raised cursor-pointer"
          aria-label="Collapse sidebar"
        >
          &#x2190;
        </button>
      </div>

      <nav className="flex-1 overflow-auto py-2 px-2">
        <SearchButton />

        <NavLink
          to="/"
          end
          className={({ isActive }) =>
            `flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors ${isActive ? 'bg-primary/10 text-primary font-semibold' : 'text-foreground hover:bg-raised'}`
          }
        >
          Home
        </NavLink>

        {calendarConnected && (
          <NavLink
            to="/calendar"
            className={({ isActive }) =>
              `flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors ${isActive ? 'bg-primary/10 text-primary font-semibold' : 'text-foreground hover:bg-raised'}`
            }
          >
            <CalendarIcon />
            Calendar
          </NavLink>
        )}

        {emailConnected && (
          <NavLink
            to="/email"
            className={({ isActive }) =>
              `flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors ${isActive ? 'bg-primary/10 text-primary font-semibold' : 'text-foreground hover:bg-raised'}`
            }
          >
            <EmailIcon />
            Email
          </NavLink>
        )}

        <div className="mt-4 mb-1 px-3 flex items-center justify-between">
          <span className="text-[11px] font-semibold text-muted uppercase tracking-wider">Spaces</span>
          <button
            onClick={() => setCreateModalOpen(true)}
            className="text-muted hover:text-foreground transition-colors p-0.5 rounded hover:bg-raised cursor-pointer"
            aria-label="Create space"
            title="New space"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              <path d="M7 3v8M3 7h8" />
            </svg>
          </button>
        </div>

        {spaces.length === 0 && (
          <div className="px-3 py-2 text-sm text-muted italic">No spaces yet</div>
        )}

        {spaces.map((space) => (
          <NavLink
            key={space.id}
            to={`/space/${space.id}`}
            className={({ isActive }) =>
              `flex items-center justify-between px-3 py-2 rounded-md text-sm transition-colors ${isActive ? 'bg-primary/10 text-primary font-semibold' : 'text-foreground hover:bg-raised'}`
            }
          >
            <span className="truncate">{space.name}</span>
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-border p-2">
        <NavLink
          to="/agents"
          className={({ isActive }) =>
            `flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors ${isActive ? 'bg-primary/10 text-primary font-semibold' : 'text-muted hover:bg-raised hover:text-foreground'}`
          }
        >
          Agents
        </NavLink>
        <NavLink
          to="/automations"
          className={({ isActive }) =>
            `flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors ${isActive ? 'bg-primary/10 text-primary font-semibold' : 'text-muted hover:bg-raised hover:text-foreground'}`
          }
        >
          Automations
        </NavLink>
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            `flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors ${isActive ? 'bg-primary/10 text-primary font-semibold' : 'text-muted hover:bg-raised hover:text-foreground'}`
          }
        >
          Settings
        </NavLink>
      </div>

      <CreateSpaceModal open={createModalOpen} onClose={() => setCreateModalOpen(false)} />
    </aside>
  );
}
