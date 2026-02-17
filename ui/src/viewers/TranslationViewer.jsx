import React, { PureComponent } from 'react';
import { Pre } from '@blueprintjs/core';

import { ErrorSection, Skeleton } from 'components/common';

import './TextViewer.scss';

class TranslationViewer extends PureComponent {
  render() {
    const { document, dir } = this.props;

    if (document.isPending) {
      return (
        <div className="outer">
          <div className="inner">
            <Skeleton.Text type="pre" length={4000} />
          </div>
        </div>
      );
    }

    const text = document.getFirst('translatedText');

    if (!text) {
      return (
        <ErrorSection
          icon="issue"
          title="No translation available"
          description="This document has not been translated yet."
        />
      );
    }

    return (
      <div className="outer">
        <div className="inner">
          <Pre className="TextViewer" dir={dir}>
            {text}
          </Pre>
        </div>
      </div>
    );
  }
}

export default TranslationViewer;
