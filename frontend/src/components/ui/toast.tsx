import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { useToastStore, type Toast } from '../../stores/toast-store';

const typeStyles: Record<string, string> = {
  info: 'bg-surface/90 border-border text-foreground',
  success: 'bg-surface/90 border-success/40 text-success',
  warning: 'bg-surface/90 border-warning/40 text-warning',
  error: 'bg-surface/90 border-destructive/40 text-destructive',
};

function ToastItem({ toast }: { toast: Toast }) {
  const removeToast = useToastStore((s) => s.removeToast);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    // Trigger enter animation on next frame
    requestAnimationFrame(() => setVisible(true));

    // Start fade-out 500ms before removal (3s total, so at 2.5s)
    const fadeTimer = setTimeout(() => setVisible(false), 2500);
    return () => clearTimeout(fadeTimer);
  }, []);

  return (
    <div
      role="status"
      className={`px-4 py-2.5 rounded-lg border shadow-lg backdrop-blur-sm text-sm transition-all duration-300 ease-out ${typeStyles[toast.type] ?? typeStyles.info} ${visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2'}`}
    >
      <div className="flex items-center gap-2">
        <span className="flex-1">{toast.message}</span>
        <button
          onClick={() => removeToast(toast.id)}
          className="text-muted hover:text-foreground transition-colors text-xs p-0.5"
          aria-label="Dismiss"
        >
          &#x2715;
        </button>
      </div>
    </div>
  );
}

export function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts);

  return createPortal(
    <div
      className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm"
      aria-live="polite"
      role="region"
    >
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} />
      ))}
    </div>,
    document.body,
  );
}
