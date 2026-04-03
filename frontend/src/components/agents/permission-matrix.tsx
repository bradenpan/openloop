import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import type { components } from '../../api/types';
import { Card, CardHeader, CardBody } from '../ui';
import { Button } from '../ui';
import { Input } from '../ui';

type Agent = components['schemas']['AgentResponse'];
type Permission = components['schemas']['AgentPermissionResponse'];
type GrantLevel = components['schemas']['GrantLevel'];
type Operation = components['schemas']['Operation'];

const OPERATIONS: Operation[] = ['read', 'create', 'edit', 'delete', 'execute'];
const GRANT_LEVELS: GrantLevel[] = ['always', 'approval', 'never'];

const grantLabel: Record<string, string> = {
  always: 'Always',
  approval: 'Approval',
  never: 'Never',
};

interface PermissionMatrixProps {
  agent: Agent;
}

export function PermissionMatrix({ agent }: PermissionMatrixProps) {
  const queryClient = useQueryClient();
  const [newResource, setNewResource] = useState('');

  const permissionsQueryKey = ['get', '/api/v1/agents/{agent_id}/permissions', { params: { path: { agent_id: agent.id } } }] as const;

  const { data, isLoading } = $api.useQuery('get', '/api/v1/agents/{agent_id}/permissions', {
    params: { path: { agent_id: agent.id } },
  });

  const setPermission = $api.useMutation('post', '/api/v1/agents/permissions', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: permissionsQueryKey });
    },
  });

  const deletePermission = $api.useMutation('delete', '/api/v1/agents/permissions/{permission_id}', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: permissionsQueryKey });
    },
  });

  const permissions: Permission[] = data ?? [];

  // Group permissions by resource pattern
  const resourcePatterns = [...new Set(permissions.map((p) => p.resource_pattern))].sort();

  // Build lookup: resource_pattern -> operation -> permission
  const permissionMap = new Map<string, Map<string, Permission>>();
  for (const p of permissions) {
    if (!permissionMap.has(p.resource_pattern)) {
      permissionMap.set(p.resource_pattern, new Map());
    }
    permissionMap.get(p.resource_pattern)!.set(p.operation, p);
  }

  const handleGrantChange = (resourcePattern: string, operation: Operation, value: string) => {
    const existing = permissionMap.get(resourcePattern)?.get(operation);

    if (value === '') {
      // Remove permission
      if (existing) {
        deletePermission.mutate({
          params: { path: { permission_id: existing.id } },
        });
      }
      return;
    }

    setPermission.mutate({
      body: {
        agent_id: agent.id,
        resource_pattern: resourcePattern,
        operation,
        grant_level: value as GrantLevel,
      },
    });
  };

  const handleAddResource = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = newResource.trim();
    if (!trimmed) return;
    // Add a default permission for the new resource so it appears in the matrix
    setPermission.mutate(
      {
        body: {
          agent_id: agent.id,
          resource_pattern: trimmed,
          operation: 'read',
          grant_level: 'approval',
        },
      },
      {
        onSuccess: () => setNewResource(''),
      },
    );
  };

  const isMutating = setPermission.isPending || deletePermission.isPending;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-foreground">
            Permissions for {agent.name}
          </h3>
        </div>
      </CardHeader>
      <CardBody className="p-0">
        {isLoading ? (
          <div className="px-4 py-6 text-center text-sm text-muted">Loading permissions...</div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border">
                    <th className="text-left px-4 py-2.5 text-xs font-semibold text-muted uppercase tracking-wider">
                      Resource
                    </th>
                    {OPERATIONS.map((op) => (
                      <th
                        key={op}
                        className="text-center px-2 py-2.5 text-xs font-semibold text-muted uppercase tracking-wider"
                      >
                        {op}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {resourcePatterns.length === 0 ? (
                    <tr>
                      <td
                        colSpan={OPERATIONS.length + 1}
                        className="px-4 py-6 text-center text-sm text-muted"
                      >
                        No permissions defined. Add a resource pattern below.
                      </td>
                    </tr>
                  ) : (
                    resourcePatterns.map((resource) => (
                      <tr key={resource} className="border-b border-border last:border-b-0 hover:bg-raised/50">
                        <td className="px-4 py-2 font-mono text-xs text-foreground whitespace-nowrap">
                          {resource}
                        </td>
                        {OPERATIONS.map((op) => {
                          const perm = permissionMap.get(resource)?.get(op);
                          return (
                            <td key={op} className="px-2 py-2 text-center">
                              <select
                                value={perm?.grant_level ?? ''}
                                onChange={(e) => handleGrantChange(resource, op, e.target.value)}
                                disabled={isMutating}
                                aria-label={`${resource} ${op} permission`}
                                className="bg-raised text-foreground border border-border rounded px-1.5 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-primary cursor-pointer disabled:opacity-50 min-w-[80px]"
                              >
                                <option value="">--</option>
                                {GRANT_LEVELS.map((gl) => (
                                  <option key={gl} value={gl}>{grantLabel[gl]}</option>
                                ))}
                              </select>
                            </td>
                          );
                        })}
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            <div className="px-4 py-3 border-t border-border">
              <form onSubmit={handleAddResource} className="flex items-end gap-2">
                <div className="flex-1">
                  <Input
                    label="Add Resource Pattern"
                    value={newResource}
                    onChange={(e) => setNewResource(e.target.value)}
                    placeholder="e.g. spaces.*, items.*, external/*"
                  />
                </div>
                <Button type="submit" size="sm" disabled={!newResource.trim() || isMutating}>
                  Add
                </Button>
              </form>
            </div>
          </>
        )}
      </CardBody>
    </Card>
  );
}
