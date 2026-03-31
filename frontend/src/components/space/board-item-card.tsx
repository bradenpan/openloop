import { useSortable } from '@dnd-kit/sortable';
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
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: item.id, data: { item } });

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
      className="bg-surface border border-border rounded-lg p-3 cursor-grab active:cursor-grabbing hover:border-primary/40 transition-colors group"
    >
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
