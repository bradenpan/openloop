import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Panel, Button } from '../ui';
import { $api } from '../../api/hooks';
import { LayoutEditor } from './layout-editor';
import { MemoryTab } from './memory-tab';
import { StagesEditor } from './stages-editor';
import { FieldEditor } from './field-editor';

type SettingsTab = 'layout' | 'stages' | 'fields' | 'memory' | 'history';

interface SpaceSettingsProps {
  spaceId: string;
  open: boolean;
  onClose: () => void;
}

const TABS: { key: SettingsTab; label: string }[] = [
  { key: 'layout', label: 'Layout' },
  { key: 'stages', label: 'Stages' },
  { key: 'fields', label: 'Fields' },
  { key: 'memory', label: 'Memory' },
  { key: 'history', label: 'History' },
];

export function SpaceSettings({ spaceId, open, onClose }: SpaceSettingsProps) {
  const [activeTab, setActiveTab] = useState<SettingsTab>('layout');
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [confirmName, setConfirmName] = useState('');
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: space } = $api.useQuery('get', '/api/v1/spaces/{space_id}', {
    params: { path: { space_id: spaceId } },
  });

  const deleteMutation = $api.useMutation('delete', '/api/v1/spaces/{space_id}', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/spaces'] });
      navigate('/');
    },
    onError: (err: unknown) => {
      const message =
        err instanceof Error ? err.message : 'Failed to delete space';
      setDeleteError(message);
    },
  });

  const spaceName = space?.name ?? '';
  const nameMatches = confirmName === spaceName && confirmName.length > 0;

  useEffect(() => {
    if (open) {
      setActiveTab('layout');
      setShowDeleteConfirm(false);
      setConfirmName('');
      setDeleteError(null);
    }
  }, [spaceId, open]);

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

      {activeTab === 'stages' && (
        <StagesEditor spaceId={spaceId} />
      )}

      {activeTab === 'fields' && (
        <FieldEditor spaceId={spaceId} />
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
      {/* Danger Zone */}
      <div className="mt-8 border border-destructive/30 rounded-lg p-4 bg-destructive/5">
        <h3 className="text-sm font-semibold text-destructive mb-1">Danger Zone</h3>
        <p className="text-xs text-muted mb-3">
          Irreversible actions that affect this entire space.
        </p>

        {!showDeleteConfirm ? (
          <Button
            variant="destructive"
            size="sm"
            onClick={() => {
              setShowDeleteConfirm(true);
              setDeleteError(null);
            }}
          >
            Delete Space
          </Button>
        ) : (
          <div className="flex flex-col gap-2">
            <p className="text-xs text-foreground">
              This will permanently delete this space and all its items,
              conversations, and documents. Type{' '}
              <span className="font-semibold">{spaceName}</span> to confirm.
            </p>
            <input
              type="text"
              value={confirmName}
              onChange={(e) => {
                setConfirmName(e.target.value);
                setDeleteError(null);
              }}
              placeholder={spaceName}
              className="w-full px-3 py-1.5 text-sm rounded-md border border-border bg-surface text-foreground placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-destructive"
              autoFocus
            />
            {deleteError && (
              <p className="text-xs text-destructive">{deleteError}</p>
            )}
            <div className="flex gap-2">
              <Button
                variant="destructive"
                size="sm"
                disabled={!nameMatches || deleteMutation.isPending}
                onClick={() =>
                  deleteMutation.mutate({
                    params: { path: { space_id: spaceId } },
                  })
                }
              >
                {deleteMutation.isPending ? 'Deleting...' : 'Confirm Delete'}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setShowDeleteConfirm(false);
                  setConfirmName('');
                  setDeleteError(null);
                }}
              >
                Cancel
              </Button>
            </div>
          </div>
        )}
      </div>
    </Panel>
  );
}
