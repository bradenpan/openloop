import { useState } from 'react';
import { $api } from '../../api/hooks';
import { useQueryClient } from '@tanstack/react-query';
import { Modal } from '../ui';
import { useToastStore } from '../../stores/toast-store';

type SystemState = 'active' | 'busy' | 'paused';

function resolveState(paused: boolean, activeSessions: number): SystemState {
  if (paused) return 'paused';
  if (activeSessions > 0) return 'busy';
  return 'active';
}

const dotColors: Record<SystemState, string> = {
  active: 'bg-success',
  busy: 'bg-warning',
  paused: 'bg-destructive',
};

const dotPulse: Record<SystemState, string> = {
  active: '',
  busy: 'animate-pulse',
  paused: '',
};

export function SystemStatus() {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const status = $api.useQuery('get', '/api/v1/system/status', {}, {
    refetchInterval: 5_000,
    staleTime: 4_000,
  });

  const emergencyStop = $api.useMutation('post', '/api/v1/system/emergency-stop', {
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/system/status'] });
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/agents/running'] });
      addToast(`System paused. ${data.tasks_interrupted} task(s) interrupted.`, 'warning');
      setConfirmOpen(false);
    },
    onError: () => {
      addToast('Failed to stop system.', 'error');
      setConfirmOpen(false);
    },
  });

  const resume = $api.useMutation('post', '/api/v1/system/resume', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/system/status'] });
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/agents/running'] });
      addToast('System resumed.', 'success');
    },
    onError: () => {
      addToast('Failed to resume system.', 'error');
    },
  });

  if (status.isLoading || !status.data) {
    return (
      <div className="flex items-center gap-2 px-2 py-1">
        <span className="inline-block w-2 h-2 rounded-full bg-raised animate-pulse" />
        <span className="text-xs text-muted">...</span>
      </div>
    );
  }

  const { paused, active_sessions } = status.data;
  const state = resolveState(paused, active_sessions);

  const label =
    state === 'paused'
      ? 'PAUSED'
      : state === 'busy'
        ? `${active_sessions} agent${active_sessions !== 1 ? 's' : ''} running`
        : 'Active';

  return (
    <>
      <div className="flex items-center gap-2">
        {/* Status dot + label */}
        <div className="flex items-center gap-1.5 px-2 py-1 rounded-md">
          <span
            className={`inline-block w-2 h-2 rounded-full ${dotColors[state]} ${dotPulse[state]}`}
            aria-hidden="true"
          />
          <span
            className={`text-xs font-medium ${
              state === 'paused' ? 'text-destructive' : 'text-muted'
            }`}
          >
            {label}
          </span>
        </div>

        {/* Stop button — visible only when agents are running */}
        {state === 'busy' && (
          <button
            onClick={() => setConfirmOpen(true)}
            className="inline-flex items-center justify-center w-6 h-6 rounded-md text-muted hover:text-destructive hover:bg-destructive/10 transition-colors cursor-pointer"
            aria-label="Stop all background work"
            title="Stop all background work"
          >
            {/* Square stop icon */}
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg">
              <rect x="1" y="1" width="10" height="10" rx="1.5" fill="currentColor" />
            </svg>
          </button>
        )}

        {/* Resume button — visible only when paused */}
        {state === 'paused' && (
          <button
            onClick={() => resume.mutate({})}
            disabled={resume.isPending}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium text-success hover:bg-success/10 transition-colors cursor-pointer disabled:opacity-50"
            aria-label="Resume system"
          >
            {/* Play triangle icon */}
            <svg width="10" height="12" viewBox="0 0 10 12" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M1 1.5V10.5L9 6L1 1.5Z" fill="currentColor" />
            </svg>
            Resume
          </button>
        )}
      </div>

      {/* Confirmation modal */}
      <Modal open={confirmOpen} onClose={() => setConfirmOpen(false)} title="Stop all background work?">
        <div className="space-y-4">
          <p className="text-sm text-muted">
            This will immediately interrupt all running agent sessions.
            Background tasks will be marked as cancelled. You can resume
            the system afterward, but interrupted tasks will not restart
            automatically.
          </p>
          <div className="flex items-center justify-end gap-3">
            <button
              onClick={() => setConfirmOpen(false)}
              className="px-4 py-2 text-sm text-muted hover:text-foreground rounded-md hover:bg-raised transition-colors cursor-pointer"
            >
              Cancel
            </button>
            <button
              onClick={() => emergencyStop.mutate({})}
              disabled={emergencyStop.isPending}
              className="px-4 py-2 text-sm font-medium text-white bg-destructive rounded-md hover:opacity-90 transition-colors cursor-pointer disabled:opacity-50"
            >
              {emergencyStop.isPending ? 'Stopping...' : 'Stop Everything'}
            </button>
          </div>
        </div>
      </Modal>
    </>
  );
}
