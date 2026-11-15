import React from 'react';

import { useArchiveUrl } from 'util/archiveUrl';

import './ImageViewer.scss';

function ImageViewer(props) {
  const { document } = props;
  const src = useArchiveUrl(document?.links?.file);
  return (
    <div className="outer">
      <div className="inner ImageViewer">
        {src && <img src={src} alt={document.getCaption()} />}
      </div>
    </div>
  );
}

export default ImageViewer;
