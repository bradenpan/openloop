import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";

/* === Types (temporary until codegen is wired up) === */

export interface SpaceResponse {
  id: string;
  name: string;
  template: string;
  description: string | null;
  settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface TodoResponse {
  id: string;
  space_id: string;
  title: string;
  status: string;
  priority: string;
  due_date: string | null;
  created_at: string;
  updated_at: string;
}

export interface ItemResponse {
  id: string;
  space_id: string;
  type: string;
  title: string;
  content: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/* === Query Hooks === */

export function useSpaces() {
  return useQuery({
    queryKey: ["spaces"],
    queryFn: () => apiFetch<SpaceResponse[]>("/spaces"),
  });
}

export function useSpace(id: string) {
  return useQuery({
    queryKey: ["spaces", id],
    queryFn: () => apiFetch<SpaceResponse>(`/spaces/${id}`),
    enabled: !!id,
  });
}

export function useTodos(spaceId?: string) {
  return useQuery({
    queryKey: ["todos", { spaceId }],
    queryFn: () => {
      const params = spaceId ? `?space_id=${spaceId}` : "";
      return apiFetch<TodoResponse[]>(`/todos${params}`);
    },
  });
}

export function useItems(spaceId: string) {
  return useQuery({
    queryKey: ["items", { spaceId }],
    queryFn: () => apiFetch<ItemResponse[]>(`/spaces/${spaceId}/items`),
    enabled: !!spaceId,
  });
}

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => apiFetch<{ status: string }>("/health"),
    retry: false,
  });
}
