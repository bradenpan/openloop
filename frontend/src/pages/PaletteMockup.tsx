import { useState, type CSSProperties } from 'react';

type Theme = 'dark' | 'light';

interface Colors {
  bg: string;
  surface: string;
  surfaceRaised: string;
  text: string;
  textMuted: string;
  accent: string;
  accentHover: string;
  accentText: string;
  border: string;
  danger: string;
  success: string;
  warning: string;
}

interface Palette {
  name: string;
  desc: string;
  font: string;
  fontLabel: string;
  dark: Colors;
  light: Colors;
}

const PALETTES: Record<string, Palette> = {
  A: {
    name: 'Slate + Cyan',
    desc: 'Cool, focused, technical — VS Code / Linear energy',
    font: "'DM Sans', sans-serif",
    fontLabel: 'DM Sans',
    dark: {
      bg: '#0f172a', surface: '#1e293b', surfaceRaised: '#334155',
      text: '#f1f5f9', textMuted: '#94a3b8',
      accent: '#06b6d4', accentHover: '#22d3ee', accentText: '#ffffff',
      border: '#334155', danger: '#ef4444', success: '#22c55e', warning: '#eab308',
    },
    light: {
      bg: '#f8fafc', surface: '#ffffff', surfaceRaised: '#f1f5f9',
      text: '#0f172a', textMuted: '#64748b',
      accent: '#0891b2', accentHover: '#06b6d4', accentText: '#ffffff',
      border: '#e2e8f0', danger: '#dc2626', success: '#16a34a', warning: '#ca8a04',
    },
  },
  B: {
    name: 'Warm Stone + Amber',
    desc: 'Warm, approachable, productive — Claude / Notion feel',
    font: "'Plus Jakarta Sans', sans-serif",
    fontLabel: 'Plus Jakarta Sans',
    dark: {
      bg: '#1c1917', surface: '#292524', surfaceRaised: '#44403c',
      text: '#fafaf9', textMuted: '#a8a29e',
      accent: '#f59e0b', accentHover: '#fbbf24', accentText: '#1c1917',
      border: '#44403c', danger: '#ef4444', success: '#22c55e', warning: '#eab308',
    },
    light: {
      bg: '#fafaf9', surface: '#ffffff', surfaceRaised: '#f5f5f4',
      text: '#1c1917', textMuted: '#78716c',
      accent: '#d97706', accentHover: '#f59e0b', accentText: '#ffffff',
      border: '#e7e5e4', danger: '#dc2626', success: '#16a34a', warning: '#ca8a04',
    },
  },
  C: {
    name: 'Neutral + Indigo',
    desc: 'Modern, balanced, versatile — Slack / Trello vibe',
    font: "'Outfit', sans-serif",
    fontLabel: 'Outfit',
    dark: {
      bg: '#171717', surface: '#262626', surfaceRaised: '#404040',
      text: '#fafafa', textMuted: '#a3a3a3',
      accent: '#6366f1', accentHover: '#818cf8', accentText: '#ffffff',
      border: '#404040', danger: '#ef4444', success: '#22c55e', warning: '#eab308',
    },
    light: {
      bg: '#fafafa', surface: '#ffffff', surfaceRaised: '#f5f5f5',
      text: '#171717', textMuted: '#737373',
      accent: '#4f46e5', accentHover: '#6366f1', accentText: '#ffffff',
      border: '#e5e5e5', danger: '#dc2626', success: '#16a34a', warning: '#ca8a04',
    },
  },
};

function Badge({ label, color, bg }: { label: string; color: string; bg: string }) {
  return (
    <span style={{
      background: bg, color, borderRadius: 12, padding: '2px 10px',
      fontSize: 12, fontWeight: 500, display: 'inline-block',
    }}>
      {label}
    </span>
  );
}

function AppPreview({ c, font }: { c: Colors; font: string }) {
  const s = {
    odinBar: {
      background: c.surface, borderBottom: `1px solid ${c.border}`,
      padding: '8px 16px', display: 'flex', alignItems: 'center', gap: 8,
    } as CSSProperties,
    sidebar: {
      width: 180, background: c.surface, borderRight: `1px solid ${c.border}`,
      padding: 12, flexShrink: 0,
    } as CSSProperties,
    sidebarItem: (active: boolean) => ({
      padding: '6px 10px', borderRadius: 6, fontSize: 13, marginBottom: 2,
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      cursor: 'pointer',
      ...(active ? { background: c.accent + '1a', color: c.accent, fontWeight: 600 } : {}),
    } as CSSProperties),
    sectionLabel: {
      color: c.textMuted, fontSize: 11, fontWeight: 600,
      textTransform: 'uppercase' as const, letterSpacing: '0.05em',
      padding: '10px 10px 4px',
    } as CSSProperties,
    statCard: (color: string) => ({
      background: c.surface, border: `1px solid ${c.border}`,
      borderRadius: 8, padding: '12px 14px',
      borderLeft: `3px solid ${color}`,
    } as CSSProperties),
    btn: (variant: 'primary' | 'secondary' | 'ghost' | 'danger') => {
      const base: CSSProperties = {
        border: 'none', borderRadius: 6, padding: '6px 16px',
        fontSize: 13, fontWeight: 500, fontFamily: font, cursor: 'pointer',
      };
      switch (variant) {
        case 'primary': return { ...base, background: c.accent, color: c.accentText };
        case 'secondary': return { ...base, background: 'transparent', color: c.text, border: `1px solid ${c.border}` };
        case 'ghost': return { ...base, background: 'transparent', color: c.textMuted };
        case 'danger': return { ...base, background: c.danger, color: '#ffffff' };
      }
    },
    input: {
      background: c.surfaceRaised, color: c.text, border: `1px solid ${c.border}`,
      borderRadius: 6, padding: '6px 12px', fontSize: 13, fontFamily: font,
      outline: 'none',
    } as CSSProperties,
  };

  return (
    <div style={{ background: c.bg, color: c.text, borderRadius: 10, border: `1px solid ${c.border}`, overflow: 'hidden', fontFamily: font }}>
      {/* Odin Bar */}
      <div style={s.odinBar}>
        <button style={{ ...s.btn('primary'), padding: '4px 10px', fontSize: 14, fontWeight: 700, lineHeight: 1 }}>+</button>
        <input
          placeholder="Ask Odin anything..."
          style={{ ...s.input, flex: 1 }}
          readOnly
        />
        <button style={{
          ...s.btn('secondary'), padding: '4px 12px', fontSize: 11, fontWeight: 600,
          display: 'flex', alignItems: 'center', gap: 4,
        }}>
          Opus <span style={{ color: c.accent }}>&#9889;</span>
        </button>
      </div>

      {/* Main layout */}
      <div style={{ display: 'flex', minHeight: 420 }}>
        {/* Sidebar */}
        <div style={s.sidebar}>
          <div style={s.sidebarItem(true)}>
            <span>Home</span>
          </div>
          <div style={s.sectionLabel}>Spaces</div>
          <div style={s.sidebarItem(false)}>
            <span>Work</span>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: c.success }} />
          </div>
          <div style={s.sidebarItem(false)}>
            <span>Personal</span>
          </div>
          <div style={s.sidebarItem(false)}>
            <span>Recruiting</span>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: c.accent }} />
          </div>
          <div style={s.sidebarItem(false)}>
            <span>Health</span>
          </div>
          <div style={{ borderTop: `1px solid ${c.border}`, marginTop: 12, paddingTop: 12 }}>
            <div style={{ ...s.sidebarItem(false), color: c.textMuted }}>Settings</div>
          </div>
        </div>

        {/* Content */}
        <div style={{ flex: 1, padding: 20, overflow: 'auto' }}>
          {/* Stats row */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 24 }}>
            {[
              { label: 'Open Todos', value: '12', color: c.accent },
              { label: 'Active Agents', value: '2', color: c.success },
              { label: 'Pending Approvals', value: '1', color: c.warning },
            ].map((stat) => (
              <div key={stat.label} style={s.statCard(stat.color)}>
                <div style={{ fontSize: 11, color: c.textMuted, marginBottom: 4 }}>{stat.label}</div>
                <div style={{ fontSize: 26, fontWeight: 700, color: stat.color }}>{stat.value}</div>
              </div>
            ))}
          </div>

          {/* Two-column: Kanban + Chat */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            {/* Mini kanban */}
            <div>
              <div style={{ fontSize: 12, color: c.textMuted, fontWeight: 600, marginBottom: 8, textTransform: 'uppercase' as const, letterSpacing: '0.04em' }}>Board Preview</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
                {[
                  { col: 'To Do', items: ['Design auth flow', 'Write API docs'] },
                  { col: 'In Progress', items: ['Refactor session mgr'] },
                  { col: 'Done', items: ['Setup CI pipeline'] },
                ].map((column) => (
                  <div key={column.col}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: c.textMuted, marginBottom: 6, padding: '0 2px' }}>{column.col}</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      {column.items.map((item) => (
                        <div key={item} style={{
                          background: c.surface, border: `1px solid ${c.border}`,
                          borderRadius: 6, padding: '8px 10px', fontSize: 12, lineHeight: 1.4,
                        }}>
                          {item}
                          <div style={{ marginTop: 4, display: 'flex', gap: 4 }}>
                            <Badge label="task" color={c.accent} bg={c.accent + '1a'} />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Chat preview */}
            <div>
              <div style={{ fontSize: 12, color: c.textMuted, fontWeight: 600, marginBottom: 8, textTransform: 'uppercase' as const, letterSpacing: '0.04em' }}>Conversation</div>
              <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 8, overflow: 'hidden' }}>
                {/* User message */}
                <div style={{ padding: '12px 16px', borderBottom: `1px solid ${c.border}` }}>
                  <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4, color: c.textMuted }}>You</div>
                  <div style={{ fontSize: 13, lineHeight: 1.5 }}>What's the status of the auth module refactor?</div>
                </div>
                {/* Assistant message */}
                <div style={{ padding: '12px 16px', background: c.surfaceRaised }}>
                  <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4, color: c.accent }}>Code Agent</div>
                  <div style={{ fontSize: 13, lineHeight: 1.5 }}>
                    The auth refactor is 70% complete. JWT validation is done, session middleware is migrated.
                  </div>
                  {/* Tool call accordion */}
                  <div style={{
                    marginTop: 8, padding: '6px 10px', background: c.bg,
                    borderRadius: 6, border: `1px solid ${c.border}`, fontSize: 12,
                    display: 'flex', alignItems: 'center', gap: 6,
                  }}>
                    <span style={{ color: c.success }}>&#10003;</span>
                    <span style={{ color: c.textMuted }}>read_file</span>
                    <span style={{ color: c.textMuted, opacity: 0.6 }}>&#8212;</span>
                    <span style={{ color: c.textMuted, fontSize: 11 }}>src/auth/middleware.ts</span>
                    <span style={{ marginLeft: 'auto', color: c.textMuted, fontSize: 11, cursor: 'pointer' }}>&#9660;</span>
                  </div>
                </div>
                {/* Approval request */}
                <div style={{ padding: '10px 16px', borderTop: `1px solid ${c.border}`, background: c.warning + '0d' }}>
                  <div style={{ fontSize: 12, marginBottom: 6 }}>
                    <span style={{ color: c.warning, fontWeight: 600 }}>Approval needed:</span>
                    <span style={{ color: c.textMuted, marginLeft: 6 }}>write_file &rarr; src/auth/session.ts</span>
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button style={{ ...s.btn('primary'), padding: '3px 14px', fontSize: 12 }}>Approve</button>
                    <button style={{ ...s.btn('secondary'), padding: '3px 14px', fontSize: 12 }}>Deny</button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Todo list preview */}
          <div style={{ marginTop: 20 }}>
            <div style={{ fontSize: 12, color: c.textMuted, fontWeight: 600, marginBottom: 8, textTransform: 'uppercase' as const, letterSpacing: '0.04em' }}>Todos</div>
            <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 8, overflow: 'hidden' }}>
              {[
                { text: 'Review PR #42 — auth middleware', done: false, due: 'Today' },
                { text: 'Call dentist', done: true, due: null },
                { text: 'Upload Q1 bloodwork results', done: false, due: 'Mar 31' },
              ].map((todo, i) => (
                <div key={i} style={{
                  padding: '8px 14px', display: 'flex', alignItems: 'center', gap: 10,
                  borderBottom: i < 2 ? `1px solid ${c.border}` : 'none',
                  opacity: todo.done ? 0.5 : 1,
                }}>
                  <div style={{
                    width: 16, height: 16, borderRadius: 4,
                    border: `2px solid ${todo.done ? c.success : c.border}`,
                    background: todo.done ? c.success : 'transparent',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    color: '#fff', fontSize: 10, flexShrink: 0,
                  }}>
                    {todo.done && '&#10003;'}
                  </div>
                  <span style={{ fontSize: 13, flex: 1, textDecoration: todo.done ? 'line-through' : 'none' }}>
                    {todo.text}
                  </span>
                  {todo.due && (
                    <span style={{
                      fontSize: 11, color: todo.due === 'Today' ? c.warning : c.textMuted,
                      fontWeight: todo.due === 'Today' ? 600 : 400,
                    }}>
                      {todo.due}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ComponentStrip({ c, font }: { c: Colors; font: string }) {
  const btnStyle = (variant: 'primary' | 'secondary' | 'ghost' | 'danger'): CSSProperties => {
    const base: CSSProperties = {
      border: 'none', borderRadius: 6, padding: '8px 20px',
      fontSize: 14, fontWeight: 500, fontFamily: font, cursor: 'pointer',
    };
    switch (variant) {
      case 'primary': return { ...base, background: c.accent, color: c.accentText };
      case 'secondary': return { ...base, background: 'transparent', color: c.text, border: `1px solid ${c.border}` };
      case 'ghost': return { ...base, background: 'transparent', color: c.textMuted };
      case 'danger': return { ...base, background: c.danger, color: '#ffffff' };
    }
  };

  return (
    <div style={{
      background: c.bg, color: c.text, padding: 20, borderRadius: 10,
      border: `1px solid ${c.border}`, fontFamily: font,
      display: 'flex', gap: 32, flexWrap: 'wrap', alignItems: 'flex-start',
    }}>
      <div>
        <div style={{ fontSize: 11, color: c.textMuted, fontWeight: 600, marginBottom: 10, textTransform: 'uppercase' as const, letterSpacing: '0.05em' }}>Buttons</div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button style={btnStyle('primary')}>Primary</button>
          <button style={btnStyle('secondary')}>Secondary</button>
          <button style={btnStyle('ghost')}>Ghost</button>
          <button style={btnStyle('danger')}>Danger</button>
        </div>
      </div>
      <div>
        <div style={{ fontSize: 11, color: c.textMuted, fontWeight: 600, marginBottom: 10, textTransform: 'uppercase' as const, letterSpacing: '0.05em' }}>Badges</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <Badge label="Default" color={c.accent} bg={c.accent + '1a'} />
          <Badge label="Success" color={c.success} bg={c.success + '1a'} />
          <Badge label="Warning" color={c.warning} bg={c.warning + '1a'} />
          <Badge label="Danger" color={c.danger} bg={c.danger + '1a'} />
          <Badge label="In Progress" color={c.accent} bg={c.accent + '1a'} />
        </div>
      </div>
      <div>
        <div style={{ fontSize: 11, color: c.textMuted, fontWeight: 600, marginBottom: 10, textTransform: 'uppercase' as const, letterSpacing: '0.05em' }}>Input</div>
        <input
          placeholder="Type something..."
          readOnly
          style={{
            background: c.surfaceRaised, color: c.text,
            border: `1px solid ${c.border}`, borderRadius: 6,
            padding: '8px 14px', fontSize: 14, fontFamily: font,
            width: 220, outline: 'none',
          }}
        />
      </div>
      <div>
        <div style={{ fontSize: 11, color: c.textMuted, fontWeight: 600, marginBottom: 10, textTransform: 'uppercase' as const, letterSpacing: '0.05em' }}>Typography</div>
        <div style={{ fontSize: 22, fontWeight: 700, marginBottom: 2 }}>Heading Text</div>
        <div style={{ fontSize: 14, lineHeight: 1.6, maxWidth: 300, color: c.textMuted }}>
          Body text at standard size. This is how descriptions, messages, and general content will look throughout the app.
        </div>
      </div>
    </div>
  );
}

function PaletteSection({ id, palette, theme }: { id: string; palette: Palette; theme: Theme }) {
  const c = theme === 'dark' ? palette.dark : palette.light;

  return (
    <section style={{ marginBottom: 48 }}>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 28, fontWeight: 700, margin: 0, fontFamily: palette.font }}>
          <span style={{ color: '#6b7280', marginRight: 8 }}>{id}.</span>
          {palette.name}
        </h2>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginTop: 4 }}>
          <span style={{ fontSize: 15, color: '#9ca3af' }}>{palette.desc}</span>
          <span style={{
            fontSize: 12, padding: '2px 10px', background: '#374151',
            color: '#d1d5db', borderRadius: 12,
          }}>
            Font: {palette.fontLabel}
          </span>
        </div>
      </div>

      {/* App Preview */}
      <div style={{ marginBottom: 12 }}>
        <AppPreview c={c} font={palette.font} />
      </div>

      {/* Component strip */}
      <ComponentStrip c={c} font={palette.font} />
    </section>
  );
}

export default function PaletteMockup() {
  const [theme, setTheme] = useState<Theme>('dark');

  return (
    <div style={{
      minHeight: '100vh', background: '#111827', color: '#f3f4f6',
      fontFamily: "'DM Sans', sans-serif",
    }}>
      {/* Header */}
      <div style={{
        position: 'sticky', top: 0, zIndex: 100,
        background: '#111827ee', backdropFilter: 'blur(12px)',
        borderBottom: '1px solid #1f2937', padding: '16px 32px',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>OpenLoop — Pick Your Palette</h1>
          <p style={{ fontSize: 14, color: '#9ca3af', margin: '4px 0 0' }}>
            Compare colors, fonts, and density. You can mix: "B colors + A font" is fine.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 4, background: '#1f2937', borderRadius: 8, padding: 3 }}>
          <button
            onClick={() => setTheme('dark')}
            style={{
              padding: '6px 16px', borderRadius: 6, border: 'none', cursor: 'pointer',
              fontSize: 13, fontWeight: 500, fontFamily: "'DM Sans', sans-serif",
              background: theme === 'dark' ? '#374151' : 'transparent',
              color: theme === 'dark' ? '#f3f4f6' : '#6b7280',
            }}
          >
            Dark
          </button>
          <button
            onClick={() => setTheme('light')}
            style={{
              padding: '6px 16px', borderRadius: 6, border: 'none', cursor: 'pointer',
              fontSize: 13, fontWeight: 500, fontFamily: "'DM Sans', sans-serif",
              background: theme === 'light' ? '#374151' : 'transparent',
              color: theme === 'light' ? '#f3f4f6' : '#6b7280',
            }}
          >
            Light
          </button>
        </div>
      </div>

      {/* Palette Sections */}
      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '32px 32px 64px' }}>
        {Object.entries(PALETTES).map(([id, palette]) => (
          <PaletteSection key={id} id={id} palette={palette} theme={theme} />
        ))}
      </div>
    </div>
  );
}
