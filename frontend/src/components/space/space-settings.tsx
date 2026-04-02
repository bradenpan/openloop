import { useEffect, useState } from 'react';
import { Panel } from '../ui';
import { LayoutEditor } from './layout-editor';
import { MemoryTab } from './memory-tab';

type SettingsTab = 'layout' | 'memory' | 'history';

interface SpaceSettingsProps {
  spaceId: string;
  open: boolean;
  onClose: () => void;
}

const TABS: { key: SettingsTab; label: string }[] = [
  { key: 'layout', label: 'Layout' },
  { key: 'memory', label: 'Memory' },
  { key: 'history', label: 'History' },
];

export function SpaceSettings({ spaceId, open, onClose }: SpaceSettingsProps) {
  const [activeTab, setActiveTab] = useState<SettingsTab>('layout');

  useEffect(() => {
    setActiveTab('layout');
  }, [spaceId]);

  return (
    <Panel open={open} onClose={onClose} title="Space Settings" width="440px">
      {/* Tab bar */}
      <div className="flex items-center gap-1 bg-raised rounded-md p-0.5 mb-4">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`flex-1 px-3 py-1.5 text-xs font-medium rounded cursor-pointer transition-colors ${
              activeTab === tab.key
                ? 'bg-surface text-foreground shadow-sm'
                : 'text-muted hover:text-foreground'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'layout' && (
        <LayoutEditor spaceId={spaceId} />
      )}

      {activeTab === 'memory' && (
        <MemoryTab spaceId={spaceId} />
      )}

      {activeTab === 'history' && (
        <div className="flex flex-col items-center gap-3 py-8">
          <p className="text-sm text-muted text-center">
            Conversation history consolidation will be available in a future update.
          </p>
          <button
            disabled
            className="px-4 py-2 text-sm font-medium rounded-md bg-raised text-muted border border-border cursor-not-allowed opacity-50"
          >
            Consolidate History
          </button>
        </div>
      )}
    </Panel>
  );
}
