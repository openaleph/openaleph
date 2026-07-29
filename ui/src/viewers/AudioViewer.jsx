import React from 'react';

import { useArchiveUrl } from 'util/archiveUrl';

import './AudioViewer.scss';

const AudioViewer = ({ document }) => {
  const src = useArchiveUrl(document?.links?.file);

  if (!src) {
    return null;
  }

  return (
    <div className="AudioViewer">
      <audio controls src={src} />
    </div>
  );
};

export default AudioViewer;
