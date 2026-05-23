import React from 'react';
import c from 'classnames';

import './Panel.scss';

export default function Panel({ className, children, ...props }) {
  return (
    <div className={c('Panel', className)} {...props}>
      {children}
    </div>
  );
}
