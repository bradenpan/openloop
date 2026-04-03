import { useEffect } from 'react';
import { $api } from '../api/hooks';

/**
 * Updates document.title with a badge count based on pending approvals
 * and unread notifications from the dashboard.
 */
export function useDocumentTitle() {
  const { data: dashboard } = $api.useQuery('get', '/api/v1/home/dashboard', {}, {
    refetchInterval: 30_000, // re-check every 30s
    refetchIntervalInBackground: false,
  });

  useEffect(() => {
    const count =
      (dashboard?.pending_approvals ?? 0) + (dashboard?.unread_notifications ?? 0);

    document.title = count > 0 ? `(${count}) OpenLoop` : 'OpenLoop';
  }, [dashboard]);
}
