import React, { PureComponent } from 'react';

import './ExportLink.scss';

class ExportLink extends PureComponent {
  render() {
    const { export_ } = this.props;

    const label = (
      <span className="ExportLink">
        {export_.file_name || export_.label}
      </span>
    );

    if (export_?.links?.download) {
      return <a href={export_.links.download}>{label}</a>;
    }
    return label;
  }
}

export default ExportLink;
