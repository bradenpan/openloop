import { Outlet } from 'react-router-dom';
import { Sidebar } from './sidebar';
import { OdinBar } from './odin-bar';
import { SearchModal } from '../search-modal';
import { useSSEConnection } from '../../hooks/use-sse';

export function AppShell() {
  useSSEConnection();

  return (
    <div className="flex h-screen bg-background text-foreground font-sans">
      <Sidebar />
      <div className="flex flex-col flex-1 min-w-0">
        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
        <OdinBar />
      </div>
      <SearchModal />
    </div>
  );
}
