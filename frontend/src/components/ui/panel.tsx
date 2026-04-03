import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

interface PanelProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  width?: string;
  className?: string;
  noPadding?: boolean;
}

export function Panel({ open, onClose, title, children, width = '400px', className = '', noPadding = false }: PanelProps) {
  const panelId = useId();
  const contentRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  // Animate in when open changes
  useEffect(() => {
    if (open) {
      // Trigger slide-in on next frame so initial translate-x-full renders first
      requestAnimationFrame(() => setVisible(true));
    } else {
      setVisible(false);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopImmediatePropagation(); onClose(); } };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  // Focus trap — recomputes focusable elements on each Tab press
  useEffect(() => {
    if (!open || !contentRef.current) return;
    const container = contentRef.current;
    const focusableSelector = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
    // Focus first element on open
    const initial = container.querySelectorAll<HTMLElement>(focusableSelector);
    initial[0]?.focus();
    const onTab = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return;
      const els = container.querySelectorAll<HTMLElement>(focusableSelector);
      if (els.length === 0) return;
      const first = els[0];
      const last = els[els.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    };
    document.addEventListener('keydown', onTab);
    return () => document.removeEventListener('keydown', onTab);
  }, [open]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-40" onClick={onClose}>
      <div className={`absolute inset-0 bg-black/30 transition-opacity duration-200 ${visible ? 'opacity-100' : 'opacity-0'}`} />
      <div
        ref={contentRef}
        className={`absolute right-0 top-0 h-full bg-surface border-l border-border shadow-xl overflow-auto transition-transform duration-200 ease-out ${visible ? 'translate-x-0' : 'translate-x-full'} ${className}`}
        style={{ width }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? panelId : undefined}
        aria-label={title ? undefined : 'Panel'}
      >
        {title && (
          <div className="px-5 py-4 border-b border-border flex items-center justify-between sticky top-0 bg-surface z-10">
            <h3 id={panelId} className="text-base font-semibold text-foreground">{title}</h3>
            <button onClick={onClose} className="text-muted hover:text-foreground transition-colors p-1 rounded-md hover:bg-raised" aria-label="Close panel">
              &#x2715;
            </button>
          </div>
        )}
        <div className={noPadding ? '' : 'p-5'}>{children}</div>
      </div>
    </div>,
    document.body,
  );
}
