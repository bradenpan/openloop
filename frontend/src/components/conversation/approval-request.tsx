import { useState } from 'react';
import { Button } from '../ui';

interface ApprovalRequestProps {
  requestId: string;
  toolName: string;
  resource: string;
  operation: string;
  onRespond: (requestId: string, approved: boolean) => void;
}

export function ApprovalRequest({
  requestId,
  toolName,
  resource,
  operation,
  onRespond,
}: ApprovalRequestProps) {
  const [responded, setResponded] = useState<'approved' | 'denied' | null>(null);
  const [loading, setLoading] = useState(false);

  const handleRespond = async (approved: boolean) => {
    setLoading(true);
    try {
      onRespond(requestId, approved);
      setResponded(approved ? 'approved' : 'denied');
    } finally {
      setLoading(false);
    }
  };

  if (responded) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 my-2 rounded-md border border-border bg-surface text-sm">
        <span className={responded === 'approved' ? 'text-success' : 'text-destructive'}>
          {responded === 'approved' ? '\u2713' : '\u2717'}
        </span>
        <span className="text-muted">
          {responded === 'approved' ? 'Approved' : 'Denied'}:{' '}
          <span className="font-mono text-xs text-foreground">{toolName}</span>
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 px-3 py-3 my-2 rounded-md border border-warning/30 bg-warning/5">
      <div className="text-sm text-foreground">
        <span className="text-warning font-medium">Approval needed: </span>
        <span className="font-mono text-xs">{toolName}</span>
        <span className="text-muted"> &rarr; </span>
        <span className="text-muted text-xs">{resource}</span>
      </div>
      {operation && (
        <div className="text-xs text-muted">
          Operation: <span className="font-mono">{operation}</span>
        </div>
      )}
      <div className="flex items-center gap-2">
        <Button size="sm" variant="primary" onClick={() => handleRespond(true)} loading={loading}>
          Approve
        </Button>
        <Button size="sm" variant="danger" onClick={() => handleRespond(false)} loading={loading}>
          Deny
        </Button>
      </div>
    </div>
  );
}
