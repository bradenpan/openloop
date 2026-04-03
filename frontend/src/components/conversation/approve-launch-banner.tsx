import { useState } from 'react';
import { $api } from '../../api/hooks';
import { Button } from '../ui';

interface ApproveLaunchBannerProps {
  taskId: string;
  /** Called after approval succeeds — parent should transition to running state */
  onApproved: (conversationId: string, taskId: string) => void;
}

export function ApproveLaunchBanner({ taskId, onApproved }: ApproveLaunchBannerProps) {
  const [dismissed, setDismissed] = useState(false);

  const approveMutation = $api.useMutation(
    'post',
    '/api/v1/background-tasks/{task_id}/approve-launch',
  );

  if (dismissed) return null;

  const handleApprove = () => {
    approveMutation.mutate(
      { params: { path: { task_id: taskId } } },
      {
        onSuccess: (data) => {
          onApproved(data.conversation_id, data.task_id);
        },
      },
    );
  };

  return (
    <div className="sticky bottom-0 z-10 border-t border-success/30 bg-success/5 backdrop-blur-sm">
      <div className="flex items-center gap-3 px-4 py-3">
        {/* Indicator dot */}
        <span className="flex items-center justify-center w-6 h-6 rounded-full bg-success/15 shrink-0">
          <span className="w-2.5 h-2.5 rounded-full bg-success animate-pulse" />
        </span>

        {/* Text */}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-foreground">
            Ready to launch autonomous execution
          </p>
          <p className="text-xs text-muted">
            The agent has enough context to proceed. Review the conversation above, then approve.
          </p>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 shrink-0">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setDismissed(true)}
            disabled={approveMutation.isPending}
          >
            Not yet
          </Button>
          <Button
            size="md"
            variant="primary"
            onClick={handleApprove}
            loading={approveMutation.isPending}
            className="bg-success hover:bg-success/90 text-white"
          >
            Approve &amp; Launch
          </Button>
        </div>
      </div>

      {/* Error */}
      {approveMutation.isError && (
        <div className="px-4 pb-2">
          <p className="text-xs text-destructive">
            Failed to approve: {(approveMutation.error as Error)?.message ?? 'Unknown error'}
          </p>
        </div>
      )}
    </div>
  );
}
