import { useCallback, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { Badge, Button, Modal } from '../ui';

interface DocumentPanelProps {
  spaceId: string;
  onSelectDocument: (documentId: string) => void;
}

const FILE_TYPE_LABELS: Record<string, string> = {
  'text/plain': 'TXT',
  'text/markdown': 'MD',
  'text/csv': 'CSV',
  'text/html': 'HTML',
  'text/css': 'CSS',
  'application/json': 'JSON',
  'application/pdf': 'PDF',
  'application/xml': 'XML',
  'image/png': 'PNG',
  'image/jpeg': 'JPG',
  'image/gif': 'GIF',
  'image/svg+xml': 'SVG',
  'application/zip': 'ZIP',
};

function fileTypeLabel(mimeType: string | null | undefined): string {
  if (!mimeType) return 'FILE';
  return FILE_TYPE_LABELS[mimeType] ?? mimeType.split('/').pop()?.toUpperCase() ?? 'FILE';
}

function formatFileSize(bytes: number | null | undefined): string {
  if (bytes == null) return '--';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function DocumentPanel({ spaceId, onSelectDocument }: DocumentPanelProps) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [tagFilter, setTagFilter] = useState<string | null>(null);

  // Drive link modal state
  const [showDriveModal, setShowDriveModal] = useState(false);
  const [driveFolderId, setDriveFolderId] = useState('');
  const [driveFolderName, setDriveFolderName] = useState('');
  const [linkingDrive, setLinkingDrive] = useState(false);
  const [driveError, setDriveError] = useState<string | null>(null);

  // Drive content viewer state
  const [driveContentId, setDriveContentId] = useState<string | null>(null);
  const [driveContent, setDriveContent] = useState<string | null>(null);
  const [loadingDriveContent, setLoadingDriveContent] = useState(false);

  // Refreshing state
  const [refreshingDs, setRefreshingDs] = useState<string | null>(null);

  const { data: docsData, isLoading } = $api.useQuery('get', '/api/v1/documents', {
    params: {
      query: {
        space_id: spaceId,
        search: searchQuery || undefined,
        tags: tagFilter || undefined,
        sort_by: 'updated',
      },
    },
  });
  const docs = docsData ?? [];

  // Fetch data sources to find linked Drive folders
  const { data: dsData } = $api.useQuery('get', '/api/v1/data-sources', {
    params: { query: { space_id: spaceId } },
  });
  const driveSources = (dsData ?? []).filter(
    (ds) => ds.source_type === 'google_drive',
  );

  // Collect all unique tags across documents for filter chips
  const allTags = Array.from(
    new Set(docs.flatMap((d) => (d.tags as string[] | null) ?? [])),
  ).sort();

  const uploadFiles = useCallback(
    async (files: FileList | File[]) => {
      setUploading(true);
      const failures: string[] = [];
      try {
        for (const file of Array.from(files)) {
          const formData = new FormData();
          formData.append('file', file);
          const resp = await fetch(`/api/v1/documents/upload?space_id=${encodeURIComponent(spaceId)}`, {
            method: 'POST',
            body: formData,
          });
          if (!resp.ok) {
            failures.push(file.name);
          }
        }
        if (failures.length > 0) {
          alert(`Upload failed for: ${failures.join(', ')}`);
        }
        queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/documents'] });
      } finally {
        setUploading(false);
      }
    },
    [spaceId, queryClient],
  );

  async function handleLinkDrive() {
    if (!driveFolderId.trim() || !driveFolderName.trim()) return;
    setLinkingDrive(true);
    setDriveError(null);
    try {
      const resp = await fetch('/api/v1/drive/link', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          space_id: spaceId,
          folder_id: driveFolderId.trim(),
          folder_name: driveFolderName.trim(),
        }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: 'Link failed' }));
        setDriveError(err.detail || 'Link failed');
        return;
      }
      setShowDriveModal(false);
      setDriveFolderId('');
      setDriveFolderName('');
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/documents'] });
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/data-sources'] });
    } catch {
      setDriveError('Failed to connect to server');
    } finally {
      setLinkingDrive(false);
    }
  }

  async function handleRefresh(dataSourceId: string) {
    setRefreshingDs(dataSourceId);
    try {
      const resp = await fetch(`/api/v1/drive/refresh/${dataSourceId}`, { method: 'POST' });
      if (!resp.ok) {
        alert('Drive refresh failed. Check your connection and try again.');
      }
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/documents'] });
    } finally {
      setRefreshingDs(null);
    }
  }

  async function handleDriveDocClick(driveFileId: string) {
    setDriveContentId(driveFileId);
    setLoadingDriveContent(true);
    setDriveContent(null);
    try {
      const resp = await fetch(`/api/v1/drive/files/${driveFileId}/content`);
      if (resp.ok) {
        const text = await resp.text();
        setDriveContent(text);
      } else {
        setDriveContent('[Failed to load content]');
      }
    } catch {
      setDriveContent('[Failed to load content]');
    } finally {
      setLoadingDriveContent(false);
    }
  }

  function handleDocClick(doc: (typeof docs)[number]) {
    if (doc.source === 'drive' && doc.drive_file_id) {
      handleDriveDocClick(doc.drive_file_id);
    } else {
      onSelectDocument(doc.id);
    }
  }

  function handleDragOver(e: React.DragEvent) {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(true);
  }

  function handleDragLeave(e: React.DragEvent) {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
    if (e.dataTransfer.files.length > 0) {
      uploadFiles(e.dataTransfer.files);
    }
  }

  function handleFileInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    if (e.target.files && e.target.files.length > 0) {
      uploadFiles(e.target.files);
      e.target.value = '';
    }
  }

  return (
    <div
      className="flex flex-col h-full"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Header */}
      <div className="px-4 py-3 border-b border-border flex items-center justify-between shrink-0">
        <h3 className="text-sm font-semibold text-foreground">
          Documents
          {docs.length > 0 && (
            <span className="ml-1.5 text-xs text-muted font-normal">({docs.length})</span>
          )}
        </h3>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setShowDriveModal(true)}
          >
            Link Drive
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => fileInputRef.current?.click()}
            loading={uploading}
          >
            Upload
          </Button>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          onChange={handleFileInputChange}
          className="hidden"
        />
      </div>

      {/* Drive folder indicators + refresh */}
      {driveSources.length > 0 && (
        <div className="px-4 py-2 border-b border-border space-y-1 shrink-0">
          {driveSources.map((ds) => (
            <div key={ds.id} className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Badge variant="default">Drive</Badge>
                <span className="text-xs text-muted truncate max-w-[160px]">{ds.name}</span>
              </div>
              <Button
                size="sm"
                variant="ghost"
                loading={refreshingDs === ds.id}
                onClick={() => handleRefresh(ds.id)}
              >
                Refresh
              </Button>
            </div>
          ))}
        </div>
      )}

      {/* Search */}
      <div className="px-4 py-2 border-b border-border shrink-0">
        <input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search documents..."
          className="w-full bg-raised text-foreground border border-border rounded-md px-2.5 py-1.5 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
        />
      </div>

      {/* Tag filter chips */}
      {allTags.length > 0 && (
        <div className="px-4 py-2 border-b border-border flex flex-wrap gap-1.5 shrink-0">
          {tagFilter && (
            <button
              onClick={() => setTagFilter(null)}
              className="text-xs text-muted hover:text-foreground cursor-pointer"
            >
              Clear
            </button>
          )}
          {allTags.map((tag) => (
            <button
              key={tag}
              onClick={() => setTagFilter(tagFilter === tag ? null : tag)}
              className="cursor-pointer"
            >
              <Badge variant={tagFilter === tag ? 'default' : 'info'}>{tag as string}</Badge>
            </button>
          ))}
        </div>
      )}

      {/* Drop overlay */}
      {dragOver && (
        <div className="px-4 py-6 text-center border-2 border-dashed border-primary bg-primary/5 m-4 rounded-lg shrink-0">
          <p className="text-sm text-primary font-medium">Drop files to upload</p>
        </div>
      )}

      {/* Document list */}
      <div className="flex-1 overflow-auto">
        {isLoading && <p className="px-4 py-6 text-sm text-muted">Loading documents...</p>}
        {!isLoading && docs.length === 0 && !dragOver && (
          <div className="px-4 py-8 text-center">
            <p className="text-sm text-muted mb-2">No documents yet</p>
            <p className="text-xs text-muted">Drag and drop files here, or click Upload</p>
          </div>
        )}
        {docs.map((doc) => (
          <button
            key={doc.id}
            onClick={() => handleDocClick(doc)}
            className="w-full text-left px-4 py-3 hover:bg-raised/50 transition-colors border-b border-border/50 cursor-pointer"
          >
            <div className="flex items-start gap-3">
              {/* File type indicator */}
              <span className="shrink-0 mt-0.5 text-[10px] font-bold text-muted bg-raised px-1.5 py-0.5 rounded">
                {fileTypeLabel(doc.mime_type)}
              </span>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <p className="text-sm text-foreground truncate">{doc.title}</p>
                  {doc.source === 'drive' && (
                    <Badge variant="default" className="text-[9px] px-1 py-0 shrink-0">
                      Drive
                    </Badge>
                  )}
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-[11px] text-muted">{formatFileSize(doc.file_size)}</span>
                  <span className="text-[11px] text-muted">
                    {new Date(doc.updated_at).toLocaleDateString()}
                  </span>
                </div>
                {doc.tags && (doc.tags as string[]).length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1.5">
                    {(doc.tags as string[]).map((tag) => (
                      <Badge key={tag} variant="info" className="text-[10px] px-1.5 py-0">
                        {tag}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </button>
        ))}
      </div>

      {/* Link Google Drive Modal */}
      <Modal
        open={showDriveModal}
        onClose={() => {
          setShowDriveModal(false);
          setDriveError(null);
        }}
        title="Link Google Drive Folder"
      >
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">
              Folder ID
            </label>
            <input
              value={driveFolderId}
              onChange={(e) => setDriveFolderId(e.target.value)}
              placeholder="e.g. 1ABC_xyz..."
              className="w-full bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
            />
            <p className="text-xs text-muted mt-1">
              Find this in the Drive folder URL after /folders/
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">
              Folder Name
            </label>
            <input
              value={driveFolderName}
              onChange={(e) => setDriveFolderName(e.target.value)}
              placeholder="My Project Docs"
              className="w-full bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
            />
          </div>
          {driveError && (
            <p className="text-sm text-destructive">{driveError}</p>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setShowDriveModal(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleLinkDrive}
              loading={linkingDrive}
              disabled={!driveFolderId.trim() || !driveFolderName.trim()}
            >
              Link Folder
            </Button>
          </div>
        </div>
      </Modal>

      {/* Drive Content Viewer Modal */}
      <Modal
        open={driveContentId !== null}
        onClose={() => {
          setDriveContentId(null);
          setDriveContent(null);
        }}
        title="Drive Document"
      >
        <div className="max-h-[60vh] overflow-auto">
          {loadingDriveContent && (
            <p className="text-sm text-muted">Loading content...</p>
          )}
          {!loadingDriveContent && driveContent !== null && (
            <pre className="text-sm text-foreground whitespace-pre-wrap font-mono bg-raised p-4 rounded-md">
              {driveContent}
            </pre>
          )}
        </div>
      </Modal>
    </div>
  );
}
