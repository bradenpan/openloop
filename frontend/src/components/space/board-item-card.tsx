import { useState, useEffect, useRef } from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { Badge } from '../ui';
import type { components } from '../../api/types';

type ItemResponse = components['schemas']['ItemResponse'];

function toTransformString(transform: { x: number; y: number; scaleX: number; scaleY: number } | null): string | undefined {
  if (!transform) return undefined;
  return `translate3d(${Math.round(transform.x)}px, ${Math.round(transform.y)}px, 0) scaleX(${transform.scaleX}) scaleY(${transform.scaleY})`;
}

interface BoardItemCardProps {
  item: ItemResponse;
  onClick: () => void;
}

export function BoardItemCard({ item, onClick }: BoardItemCardProps) {
  const queryClient = useQueryClient();
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: item.id, data: { item } });

  const [confirmArchive, setConfirmArchive] = useState(false);
  const confirmTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Reset confirm state after 3 seconds
  useEffect(() => {
    if (confirmArchive) {
      confirmTimer.current = setTimeout(() => setConfirmArchive(false), 3000);
      return () => { if (confirmTimer.current) clearTimeout(confirmTimer.current); };
    }
  }, [confirmArchive]);

  const archiveItem = $api.useMutation('post', '/api/v1/items/{item_id}/archive', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/items'] });
    },
  });

  const style = {
    transform: toTransformString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      onClick={onClick}
      className="bg-surface border border-border rounded-lg p-3 cursor-grab active:cursor-grabbing hover:border-primary/40 transition-colors group relative"
    >
      <button
        onPointerDown={(e) => e.stopPropagation()}
        onClick={(e) => {
          e.stopPropagation();
          if (confirmArchive) {
            archiveItem.mutate({ params: { path: { item_id: item.id } } });
            setConfirmArchive(false);
          } else {
            setConfirmArchive(true);
          }
        }}
        onBlur={() => setConfirmArchive(false)}
        className={`absolute top-1.5 right-1.5 opacity-0 group-hover:opacity-100 transition-all cursor-pointer p-1 rounded ${
          confirmArchive
            ? 'text-destructive bg-destructive/10 opacity-100'
            : 'text-muted hover:text-foreground hover:bg-raised'
        }`}
        aria-label={confirmArchive ? 'Confirm archive' : 'Archive item'}
        title={confirmArchive ? 'Click again to confirm' : 'Archive'}
      >
        {confirmArchive ? (
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M11.5 3.5L5.5 10l-3-3" />
          </svg>
        ) : (
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="1" y="2" width="14" height="4" rx="1" />
            <path d="M2 6v7a1 1 0 001 1h10a1 1 0 001-1V6" />
            <path d="M6 9h4" />
          </svg>
        )}
      </button>

      <p className="text-sm font-medium text-foreground leading-snug mb-2 group-hover:text-primary transition-colors">
        {item.title}
      </p>

      <div className="flex items-center gap-1.5 flex-wrap">
        <Badge variant={item.item_type === 'task' ? 'default' : 'info'}>
          {item.item_type}
        </Badge>

        {item.priority != null && (
          <Badge variant={item.priority >= 3 ? 'danger' : item.priority >= 2 ? 'warning' : 'info'}>
            P{item.priority}
          </Badge>
        )}

        {item.due_date && (
          <span className="text-[11px] text-muted">
            {new Date(item.due_date).toLocaleDateString()}
          </span>
        )}
      </div>
    </div>
  );
}
