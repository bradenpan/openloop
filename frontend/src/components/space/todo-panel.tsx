import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { Button } from '../ui';

interface TodoPanelProps {
  spaceId: string;
  collapsed: boolean;
  onToggle: () => void;
}

export function TodoPanel({ spaceId, collapsed, onToggle }: TodoPanelProps) {
  const queryClient = useQueryClient();
  const [newTitle, setNewTitle] = useState('');

  const { data: todosData, isLoading } = $api.useQuery('get', '/api/v1/todos', {
    params: { query: { space_id: spaceId } },
  });
  const todos = todosData ?? [];

  const createTodo = $api.useMutation('post', '/api/v1/todos', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/todos'] });
      setNewTitle('');
    },
  });

  const updateTodo = $api.useMutation('patch', '/api/v1/todos/{todo_id}', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/todos'] });
    },
  });

  const deleteTodo = $api.useMutation('delete', '/api/v1/todos/{todo_id}', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/todos'] });
    },
  });

  function handleAdd(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key !== 'Enter' || !newTitle.trim()) return;
    createTodo.mutate({
      body: { space_id: spaceId, title: newTitle.trim() },
    });
  }

  function handleToggle(todoId: string, currentDone: boolean) {
    updateTodo.mutate({
      params: { path: { todo_id: todoId } },
      body: { is_done: !currentDone },
    });
  }

  function handleDelete(todoId: string) {
    deleteTodo.mutate({
      params: { path: { todo_id: todoId } },
    });
  }

  if (collapsed) {
    return (
      <div className="flex flex-col items-center py-3 w-10 shrink-0 bg-surface border-r border-border">
        <button
          onClick={onToggle}
          className="text-muted hover:text-foreground transition-colors p-1.5 rounded-md hover:bg-raised cursor-pointer"
          aria-label="Expand todo panel"
          title="Todos"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="2" y="2" width="12" height="12" rx="2" />
            <path d="M5 8h6M8 5v6" />
          </svg>
        </button>
        <span className="text-[10px] text-muted mt-1 [writing-mode:vertical-rl] rotate-180">Todos</span>
      </div>
    );
  }

  const openTodos = todos.filter((t) => !t.is_done);
  const doneTodos = todos.filter((t) => t.is_done);

  return (
    <div className="flex flex-col w-72 min-w-[256px] shrink-0 bg-surface border-r border-border">
      {/* Header */}
      <div className="px-3 py-2.5 border-b border-border flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">
          Todos
          {openTodos.length > 0 && (
            <span className="ml-1.5 text-xs text-muted font-normal">({openTodos.length})</span>
          )}
        </h3>
        <button
          onClick={onToggle}
          className="text-muted hover:text-foreground transition-colors p-1 rounded-md hover:bg-raised cursor-pointer"
          aria-label="Collapse todo panel"
        >
          &#x2190;
        </button>
      </div>

      {/* Add input */}
      <div className="px-3 py-2 border-b border-border">
        <input
          value={newTitle}
          onChange={(e) => setNewTitle(e.target.value)}
          onKeyDown={handleAdd}
          placeholder="Add todo, press Enter"
          disabled={createTodo.isPending}
          className="w-full bg-raised text-foreground border border-border rounded-md px-2.5 py-1.5 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
        />
      </div>

      {/* Todo list */}
      <div className="flex-1 overflow-auto">
        {isLoading && <p className="px-3 py-4 text-sm text-muted">Loading...</p>}

        {!isLoading && todos.length === 0 && (
          <p className="px-3 py-4 text-sm text-muted italic">No todos yet</p>
        )}

        {/* Open todos */}
        {openTodos.map((todo) => (
          <TodoRow
            key={todo.id}
            todo={todo}
            onToggle={() => handleToggle(todo.id, todo.is_done)}
            onDelete={() => handleDelete(todo.id)}
          />
        ))}

        {/* Done todos */}
        {doneTodos.length > 0 && (
          <>
            <div className="px-3 pt-3 pb-1">
              <span className="text-[11px] text-muted uppercase tracking-wider font-medium">
                Completed ({doneTodos.length})
              </span>
            </div>
            {doneTodos.map((todo) => (
              <TodoRow
                key={todo.id}
                todo={todo}
                onToggle={() => handleToggle(todo.id, todo.is_done)}
                onDelete={() => handleDelete(todo.id)}
              />
            ))}
          </>
        )}
      </div>
    </div>
  );
}

interface TodoRowProps {
  todo: {
    id: string;
    title: string;
    is_done: boolean;
    due_date: string | null;
  };
  onToggle: () => void;
  onDelete: () => void;
}

function TodoRow({ todo, onToggle, onDelete }: TodoRowProps) {
  return (
    <div className="group flex items-start gap-2 px-3 py-2 hover:bg-raised/50 transition-colors">
      <button
        onClick={onToggle}
        className={`mt-0.5 w-4 h-4 shrink-0 rounded border cursor-pointer transition-colors ${
          todo.is_done
            ? 'bg-primary border-primary text-primary-foreground'
            : 'border-border hover:border-primary'
        } flex items-center justify-center`}
        aria-label={todo.is_done ? 'Mark incomplete' : 'Mark complete'}
      >
        {todo.is_done && (
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M2 5l2.5 2.5L8 3" />
          </svg>
        )}
      </button>

      <div className="flex-1 min-w-0">
        <p className={`text-sm leading-snug ${todo.is_done ? 'line-through text-muted' : 'text-foreground'}`}>
          {todo.title}
        </p>
        {todo.due_date && (
          <span className="text-[11px] text-muted">
            {new Date(todo.due_date).toLocaleDateString()}
          </span>
        )}
      </div>

      <button
        onClick={onDelete}
        className="opacity-0 group-hover:opacity-100 text-muted hover:text-destructive transition-all p-0.5 rounded cursor-pointer shrink-0"
        aria-label="Delete todo"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M3 3l8 8M11 3l-8 8" />
        </svg>
      </button>
    </div>
  );
}
