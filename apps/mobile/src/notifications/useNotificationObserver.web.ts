import { useEffect } from 'react';

import { flushEvents } from './queue';

/** Web preview: no push notifications in the browser; just send anything queued earlier. */
export function useNotificationObserver(enabled: boolean) {
  useEffect(() => {
    if (enabled) void flushEvents();
  }, [enabled]);
}
