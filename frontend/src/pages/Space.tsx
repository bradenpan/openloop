import { useUIStore } from "@/stores/ui-store";
import { Card, CardHeader, CardBody, Badge, Button } from "@/components/ui";

const PLACEHOLDER_TODOS = [
  { id: "t1", title: "Update resume", status: "in_progress", priority: "high" },
  { id: "t2", title: "Apply to 5 companies", status: "todo", priority: "high" },
  { id: "t3", title: "Practice system design", status: "todo", priority: "medium" },
  { id: "t4", title: "Follow up on interviews", status: "done", priority: "low" },
];

const priorityVariant: Record<string, "danger" | "warning" | "info" | "default"> = {
  high: "danger",
  medium: "warning",
  low: "info",
};

const statusLabel: Record<string, string> = {
  todo: "TODO",
  in_progress: "WIP",
  done: "DONE",
};

function Space() {
  const currentSpaceId = useUIStore((s) => s.currentSpaceId);

  return (
    <div className="p-6 max-w-4xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-[var(--text-2xl)] font-bold text-[var(--color-text-primary)]">
            Space #{currentSpaceId ?? "?"}
          </h1>
          <p className="text-[var(--text-sm)] text-[var(--color-text-tertiary)] font-mono mt-1">
            // Placeholder space view
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" size="sm">Edit</Button>
          <Button variant="primary" size="sm">+ Add Todo</Button>
        </div>
      </div>

      {/* Todos */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <span>Todos</span>
            <Badge variant="default">{PLACEHOLDER_TODOS.length}</Badge>
          </div>
        </CardHeader>
        <CardBody className="!p-0">
          <div className="divide-y divide-[var(--color-border-subtle)]">
            {PLACEHOLDER_TODOS.map((todo) => (
              <div
                key={todo.id}
                className="flex items-center justify-between px-4 py-2.5 hover:bg-[var(--color-bg-hover)] transition-colors"
              >
                <div className="flex items-center gap-3">
                  <Badge variant={priorityVariant[todo.priority] ?? "default"}>
                    {todo.priority.toUpperCase()}
                  </Badge>
                  <span
                    className={[
                      "text-[var(--text-sm)]",
                      todo.status === "done"
                        ? "text-[var(--color-text-tertiary)] line-through"
                        : "text-[var(--color-text-primary)]",
                    ].join(" ")}
                  >
                    {todo.title}
                  </span>
                </div>
                <span className="text-[var(--text-xs)] font-mono text-[var(--color-text-tertiary)]">
                  {statusLabel[todo.status] ?? todo.status}
                </span>
              </div>
            ))}
          </div>
        </CardBody>
      </Card>
    </div>
  );
}

export default Space;
