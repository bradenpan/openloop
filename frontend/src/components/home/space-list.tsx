import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { components } from '../../api/types';
import { Card, CardBody, Badge, Button } from '../ui';
import { CreateSpaceModal } from './create-space-modal';

type Space = components['schemas']['SpaceResponse'];

interface SpaceListProps {
  spaces: Space[] | undefined;
  isLoading: boolean;
}

const templateVariant: Record<string, 'default' | 'success' | 'warning' | 'danger' | 'info'> = {
  project: 'default',
  crm: 'success',
  knowledge_base: 'warning',
  simple: 'info',
};

const templateLabel: Record<string, string> = {
  project: 'Project',
  crm: 'Database',
  knowledge_base: 'Knowledge Base',
  simple: 'Simple',
};

function Skeleton() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {[1, 2, 3].map((i) => (
        <Card key={i}>
          <CardBody className="space-y-2">
            <div className="h-4 w-24 rounded bg-raised animate-pulse" />
            <div className="h-3 w-full rounded bg-raised animate-pulse" />
            <div className="h-5 w-16 rounded-full bg-raised animate-pulse" />
          </CardBody>
        </Card>
      ))}
    </div>
  );
}

export function SpaceList({ spaces, isLoading }: SpaceListProps) {
  const navigate = useNavigate();
  const [modalOpen, setModalOpen] = useState(false);

  if (isLoading) return <Skeleton />;

  return (
    <>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {spaces?.map((space) => (
          <Card
            key={space.id}
            className="cursor-pointer hover:border-primary/50 transition-colors duration-150"
          >
            <CardBody
              className="space-y-1.5"
              onClick={() => navigate(`/space/${space.id}`)}
            >
              <div className="flex items-start justify-between gap-2">
                <h3 className="text-sm font-semibold text-foreground truncate">{space.name}</h3>
                <Badge variant={templateVariant[space.template] ?? 'info'} className="shrink-0">
                  {templateLabel[space.template] ?? space.template}
                </Badge>
              </div>
              {space.description && (
                <p className="text-xs text-muted line-clamp-2">{space.description}</p>
              )}
            </CardBody>
          </Card>
        ))}

        {/* Create Space card */}
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className="border border-dashed border-border rounded-lg flex items-center justify-center gap-2 py-6 text-muted hover:text-foreground hover:border-foreground/30 transition-colors duration-150 cursor-pointer"
        >
          <span className="text-lg leading-none">+</span>
          <span className="text-sm font-medium">Create Space</span>
        </button>
      </div>

      <CreateSpaceModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </>
  );
}
