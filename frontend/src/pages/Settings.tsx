import { Button } from '../components/ui';
import { useUIStore, type PaletteId } from '../stores/ui-store';

const palettes: { id: PaletteId; name: string; desc: string }[] = [
  { id: 'slate-cyan', name: 'Slate + Cyan', desc: 'Cool, focused, technical' },
  { id: 'warm-amber', name: 'Warm Stone + Amber', desc: 'Warm, approachable, productive' },
  { id: 'neutral-indigo', name: 'Neutral + Indigo', desc: 'Modern, balanced, versatile' },
];

export default function Settings() {
  const palette = useUIStore((s) => s.palette);
  const theme = useUIStore((s) => s.theme);
  const setPalette = useUIStore((s) => s.setPalette);
  const toggleTheme = useUIStore((s) => s.toggleTheme);

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-bold mb-6">Settings</h1>

      <section className="mb-8">
        <h2 className="text-lg font-semibold mb-4">Appearance</h2>

        <div className="mb-6">
          <div className="text-sm font-medium text-muted mb-2">Theme</div>
          <Button variant="secondary" onClick={toggleTheme}>
            {theme === 'dark' ? 'Dark' : 'Light'} — click to toggle
          </Button>
        </div>

        <div>
          <div className="text-sm font-medium text-muted mb-2">Color Palette</div>
          <div className="grid gap-3">
            {palettes.map((p) => (
              <button
                key={p.id}
                onClick={() => setPalette(p.id)}
                className={`flex items-center gap-3 p-3 rounded-lg border text-left transition-colors cursor-pointer ${
                  palette === p.id
                    ? 'border-primary bg-primary/10'
                    : 'border-border hover:bg-raised'
                }`}
              >
                <div className={`w-3 h-3 rounded-full shrink-0 ${palette === p.id ? 'bg-primary' : 'bg-muted'}`} />
                <div>
                  <div className="text-sm font-medium">{p.name}</div>
                  <div className="text-xs text-muted">{p.desc}</div>
                </div>
              </button>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
