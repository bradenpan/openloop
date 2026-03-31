import { useUIStore } from "@/stores/ui-store";
import { Card, CardHeader, CardBody, Button } from "@/components/ui";

function Settings() {
  const theme = useUIStore((s) => s.theme);
  const toggleTheme = useUIStore((s) => s.toggleTheme);

  return (
    <div className="p-6 max-w-2xl">
      <div className="mb-6">
        <h1 className="text-[var(--text-2xl)] font-bold text-[var(--color-text-primary)]">
          Settings
        </h1>
        <p className="text-[var(--text-sm)] text-[var(--color-text-tertiary)] font-mono mt-1">
          // System configuration
        </p>
      </div>

      <div className="space-y-4">
        {/* Appearance */}
        <Card>
          <CardHeader>Appearance</CardHeader>
          <CardBody>
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[var(--text-sm)] font-medium text-[var(--color-text-primary)]">
                  Theme
                </div>
                <div className="text-[var(--text-xs)] text-[var(--color-text-tertiary)] mt-0.5">
                  Switch between dark and light mode
                </div>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={toggleTheme}
              >
                {theme === "dark" ? "Switch to Light" : "Switch to Dark"}
              </Button>
            </div>
          </CardBody>
        </Card>

        {/* Connection */}
        <Card>
          <CardHeader>Connection</CardHeader>
          <CardBody>
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[var(--text-sm)] font-medium text-[var(--color-text-primary)]">
                  Backend API
                </div>
                <div className="text-[var(--text-xs)] text-[var(--color-text-tertiary)] font-mono mt-0.5">
                  /api/v1
                </div>
              </div>
              <span className="text-[var(--text-xs)] font-mono text-[var(--color-text-tertiary)]">
                Not connected
              </span>
            </div>
          </CardBody>
        </Card>

        {/* About */}
        <Card>
          <CardHeader>About</CardHeader>
          <CardBody>
            <div className="space-y-2">
              <div className="flex justify-between text-[var(--text-sm)]">
                <span className="text-[var(--color-text-secondary)]">Version</span>
                <span className="font-mono text-[var(--color-text-primary)]">0.1.0</span>
              </div>
              <div className="flex justify-between text-[var(--text-sm)]">
                <span className="text-[var(--color-text-secondary)]">Stack</span>
                <span className="font-mono text-[var(--color-text-primary)]">React 19 + Vite</span>
              </div>
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

export default Settings;
