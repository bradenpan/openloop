import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { Panel, Button, Badge, Modal } from '../ui';

interface DocumentViewerProps {
  documentId: string | null;
  open: boolean;
  onClose: () => void;
}

function formatFileSize(bytes: number | null | undefined): string {
  if (bytes == null) return '--';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const TEXT_MIME_PREFIXES = ['text/', 'application/json', 'application/xml'];

function isTextMime(mimeType: string | null | undefined): boolean {
  if (!mimeType) return false;
  return TEXT_MIME_PREFIXES.some((prefix) => mimeType.startsWith(prefix));
}

export function DocumentViewer({ documentId, open, onClose }: DocumentViewerProps) {
  const queryClient = useQueryClient();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [editingTags, setEditingTags] = useState(false);
  const [tagInput, setTagInput] = useState('');
  const [textContent, setTextContent] = useState<string | null>(null);
  const [loadingContent, setLoadingContent] = useState(false);

  const { data: doc } = $api.useQuery(
    'get',
    '/api/v1/documents/{document_id}',
    { params: { path: { document_id: documentId! } } },
    { enabled: open && documentId != null },
  );

  const updateDoc = $api.useMutation('patch', '/api/v1/documents/{document_id}', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/documents'] });
      queryClient.invalidateQueries({
        queryKey: ['get', '/api/v1/documents/{document_id}', { params: { path: { document_id: documentId! } } }],
      });
    },
  });

  const deleteDoc = $api.useMutation('delete', '/api/v1/documents/{document_id}', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/documents'] });
      setConfirmDelete(false);
      onClose();
    },
  });

  // Fetch text content for text files
  useEffect(() => {
    if (!open || !documentId || !doc) {
      setTextContent(null);
      return;
    }
    if (!doc.local_path || !isTextMime(doc.mime_type)) {
      setTextContent(null);
      return;
    }
    setLoadingContent(true);
    fetch(`/api/v1/documents/${documentId}/content`)
      .then((res) => {
        if (res.ok) return res.text();
        return null;
      })
      .then((text) => setTextContent(text ?? null))
      .catch(() => setTextContent(null))
      .finally(() => setLoadingContent(false));
  }, [open, documentId, doc]);

  // Reset tag editing state when doc changes
  useEffect(() => {
    if (doc) {
      setTagInput(((doc.tags as string[] | null) ?? []).join(', '));
      setEditingTags(false);
    }
  }, [doc?.id]);

  function handleSaveTags() {
    if (!documentId) return;
    const tags = tagInput
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean);
    updateDoc.mutate({
      params: { path: { document_id: documentId } },
      body: { tags },
    });
    setEditingTags(false);
  }

  function handleDelete() {
    if (!documentId) return;
    deleteDoc.mutate({
      params: { path: { document_id: documentId } },
    });
  }

  function handleDownload() {
    if (!documentId) return;
    window.open(`/api/v1/documents/${documentId}/content`, '_blank');
  }

  if (!open || !documentId) return null;

  return (
    <>
      <Panel open={open} onClose={onClose} title="Document" width="520px">
        {!doc ? (
          <p className="text-sm text-muted">Loading...</p>
        ) : (
          <div className="flex flex-col gap-5">
            {/* Title */}
            <div>
              <h2 className="text-lg font-semibold text-foreground break-words">{doc.title}</h2>
              <div className="flex items-center gap-2 mt-1.5 text-xs text-muted">
                <span>{doc.source}</span>
                {doc.mime_type && (
                  <>
                    <span className="text-border">|</span>
                    <span>{doc.mime_type}</span>
                  </>
                )}
                {doc.file_size != null && (
                  <>
                    <span className="text-border">|</span>
                    <span>{formatFileSize(doc.file_size)}</span>
                  </>
                )}
              </div>
            </div>

            {/* Tags */}
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <label className="text-xs font-medium text-muted uppercase tracking-wider">Tags</label>
                <button
                  onClick={() => setEditingTags(!editingTags)}
                  className="text-xs text-primary hover:underline cursor-pointer"
                >
                  {editingTags ? 'Cancel' : 'Edit'}
                </button>
              </div>
              {editingTags ? (
                <div className="flex gap-2">
                  <input
                    value={tagInput}
                    onChange={(e) => setTagInput(e.target.value)}
                    placeholder="tag1, tag2, tag3"
                    className="flex-1 bg-raised text-foreground border border-border rounded-md px-2.5 py-1.5 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleSaveTags();
                    }}
                  />
                  <Button size="sm" onClick={handleSaveTags} loading={updateDoc.isPending}>
                    Save
                  </Button>
                </div>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {doc.tags && (doc.tags as string[]).length > 0 ? (
                    (doc.tags as string[]).map((tag) => (
                      <Badge key={tag} variant="info">{tag}</Badge>
                    ))
                  ) : (
                    <span className="text-xs text-muted italic">No tags</span>
                  )}
                </div>
              )}
            </div>

            {/* Dates */}
            <div className="flex items-center gap-4 text-xs text-muted">
              <span>Created {new Date(doc.created_at).toLocaleString()}</span>
              <span>Updated {new Date(doc.updated_at).toLocaleString()}</span>
            </div>

            {/* Content preview or download */}
            {doc.local_path && isTextMime(doc.mime_type) ? (
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-medium text-muted uppercase tracking-wider">Content</label>
                {loadingContent ? (
                  <p className="text-sm text-muted">Loading content...</p>
                ) : textContent != null ? (
                  <pre className="bg-raised border border-border rounded-md p-3 text-xs text-foreground font-mono overflow-auto max-h-80 whitespace-pre-wrap break-words">
                    {textContent}
                  </pre>
                ) : (
                  <p className="text-xs text-muted italic">Content unavailable</p>
                )}
              </div>
            ) : doc.local_path ? (
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-medium text-muted uppercase tracking-wider">File</label>
                <Button variant="secondary" size="sm" onClick={handleDownload} className="self-start">
                  Download
                </Button>
              </div>
            ) : null}

            {/* Actions */}
            <div className="flex items-center justify-between pt-2 border-t border-border">
              {doc.local_path && (
                <Button variant="secondary" size="sm" onClick={handleDownload}>
                  Download
                </Button>
              )}
              <Button variant="danger" size="sm" onClick={() => setConfirmDelete(true)}>
                Delete
              </Button>
            </div>
          </div>
        )}
      </Panel>

      {/* Delete confirmation modal */}
      <Modal open={confirmDelete} onClose={() => setConfirmDelete(false)} title="Delete Document">
        <p className="text-sm text-foreground mb-4">
          Are you sure you want to delete <strong>{doc?.title}</strong>? This cannot be undone.
        </p>
        <div className="flex justify-end gap-3">
          <Button variant="secondary" onClick={() => setConfirmDelete(false)}>
            Cancel
          </Button>
          <Button variant="danger" onClick={handleDelete} loading={deleteDoc.isPending}>
            Delete
          </Button>
        </div>
      </Modal>
    </>
  );
}
