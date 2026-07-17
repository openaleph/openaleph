import React from 'react';

import { useArchiveUrl } from 'util/archiveUrl';

const VideoViewer = ({ document }) => {
  const src = useArchiveUrl(document?.links?.file);

  if (!src) {
    return null;
  }

  return (
    <div className="outer">
      <div className="inner VideoViewer">
        <video controls width="100%" src={src} />
      </div>
    </div>
  );
};

export default VideoViewer;
