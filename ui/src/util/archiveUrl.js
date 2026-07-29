import { useEffect, useState } from 'react';

import { endpoint } from 'app/api';

// Archive links in entity payloads (links.file/pdf/csv) point to the resolve
// endpoint, which checks permissions and issues a short-lived signed archive
// URL. Browser-native consumers (img/audio/video tags, pdf.js, papaparse,
// anchor downloads) fetch URLs without the session's Authorization header,
// so they cannot follow that link directly on non-public collections.
// Instead, we resolve the link through the authenticated API client first
// and hand the fresh signed URL to the consumer.
export function resolveArchiveUrl(link) {
  if (!link) {
    return Promise.resolve(null);
  }
  return endpoint
    .get(link, { params: { redirect: false } })
    .then((response) => response.data?.url || null);
}

// Hook version for use in rendering: returns null while the link is being
// resolved (or when it cannot be resolved), the signed URL afterwards.
export function useArchiveUrl(link) {
  const [url, setUrl] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setUrl(null);
    resolveArchiveUrl(link)
      .then((resolved) => {
        if (!cancelled) {
          setUrl(resolved);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setUrl(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [link]);

  return url;
}
