import { useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

interface PanelProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  width?: string;
  className?: string;
}

export function Panel({ open, onClose, title, children, width = '400px', className = '' }: PanelProps) {
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  // Focus trap
  useEffect(() => {
    if (!open || !contentRef.current) return;
    const els = contentRef.current.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    const first = els[0];
    const last = els[els.length - 1];
    first?.focus();
    const onTab = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return;
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    };
    document.addEventListener('keydown', onTab);
    return () => document.removeEventListener('keydown', onTab);
  }, [open]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-40" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        ref={contentRef}
        className={`absolute right-0 top-0 h-full bg-surface border-l border-border shadow-xl overflow-auto ${className}`}
        style={{ width }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        {title && (
          <div className="px-5 py-4 border-b border-border flex items-center justify-between sticky top-0 bg-surface z-10">
            <h3 className="text-base font-semibold text-foreground">{title}</h3>
            <button onClick={onClose} className="text-muted hover:text-foreground transition-colors p-1 rounded-md hover:bg-raised" aria-label="Close panel">
              &#x2715;
            </button>
          </div>
        )}
        <div className="p-5">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
