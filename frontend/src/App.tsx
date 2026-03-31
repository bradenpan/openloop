import { useEffect } from "react";
import { useUIStore } from "@/stores/ui-store";
import { Sidebar } from "@/components/layout/sidebar";
import { OdinBar } from "@/components/layout/odin-bar";
import Home from "@/pages/Home";
import Space from "@/pages/Space";
import Settings from "@/pages/Settings";

function RouteRenderer() {
  const route = useUIStore((s) => s.currentRoute);

  if (route === "/settings") return <Settings />;
  if (route.startsWith("/spaces/")) return <Space />;
  return <Home />;
}

function App() {
  const navigate = useUIStore((s) => s.navigate);

  // Sync browser URL on initial load and popstate
  useEffect(() => {
    // Set initial route from URL
    const initialPath = window.location.pathname;
    if (initialPath !== "/") {
      useUIStore.setState({ currentRoute: initialPath });
      // Extract space ID if on space route
      const spaceMatch = initialPath.match(/^\/spaces\/(.+)$/);
      if (spaceMatch?.[1]) {
        useUIStore.setState({ currentSpaceId: spaceMatch[1] });
      }
    }

    function handlePopState() {
      const path = window.location.pathname;
      useUIStore.setState({ currentRoute: path });
      const spaceMatch = path.match(/^\/spaces\/(.+)$/);
      useUIStore.setState({
        currentSpaceId: spaceMatch?.[1] ?? null,
      });
    }

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [navigate]);

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--color-bg-primary)] text-[var(--color-text-primary)]">
      <Sidebar />
      <div className="flex flex-col flex-1 min-w-0">
        <OdinBar />
        <main className="flex-1 overflow-y-auto">
          <RouteRenderer />
        </main>
      </div>
    </div>
  );
}

export default App;
