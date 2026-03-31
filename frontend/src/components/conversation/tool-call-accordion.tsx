import { useState } from 'react';

interface ToolCallAccordionProps {
  toolName: string;
  status: 'started' | 'completed' | 'failed';
  resultSummary?: string;
}

function StatusIcon({ status }: { status: ToolCallAccordionProps['status'] }) {
  switch (status) {
    case 'started':
      return (
        <span className="inline-block w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      );
    case 'completed':
      return <span className="text-success text-sm">&#10003;</span>;
    case 'failed':
      return <span className="text-destructive text-sm">&#10007;</span>;
  }
}

export function ToolCallAccordion({ toolName, status, resultSummary }: ToolCallAccordionProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border border-border rounded-md my-2 overflow-hidden">
      <button
        type="button"
        className="w-full flex items-center gap-2 px-3 py-2 text-sm text-foreground bg-surface hover:bg-raised transition-colors cursor-pointer"
        onClick={() => setExpanded((prev) => !prev)}
      >
        <span
          className="text-muted text-xs transition-transform duration-150"
          style={{ transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)' }}
        >
          &#9654;
        </span>
        <StatusIcon status={status} />
        <span className="font-mono text-xs">{toolName}</span>
        <span className="text-muted text-xs ml-auto">{status}</span>
      </button>
      {expanded && (
        <div className="px-3 py-2 border-t border-border bg-background text-sm text-muted whitespace-pre-wrap">
          {resultSummary || (status === 'started' ? 'Running...' : 'No result available.')}
        </div>
      )}
    </div>
  );
}
