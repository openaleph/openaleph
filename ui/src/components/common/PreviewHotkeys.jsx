import React from 'react';
import queryString from 'query-string';
import { defineMessages, injectIntl } from 'react-intl';
import { compose } from 'redux';

import withRouter from 'app/withRouter';
import HotkeysContainer from './HotkeysContainer';
import togglePreview from 'util/togglePreview';

const messages = defineMessages({
  next: {
    id: 'preview_hotkeys.next',
    defaultMessage: 'Preview next result',
  },
  previous: {
    id: 'preview_hotkeys.previous',
    defaultMessage: 'Preview previous result',
  },
  close_preview: {
    id: 'preview_hotkeys.close_preview',
    defaultMessage: 'Close preview',
  },
});

// Shared preview-navigation scaffolding for faceted-search surfaces.
// Owns the j/k/up/down/esc hotkeys and the `togglePreview` dance that
// every Entity tab mode, `FacetedEntitySearch`, and the Screening
// screen used to copy-paste. Caller just provides `result` (for the
// results array) + a `groupLabel` for the help overlay, and wraps
// its body in `<PreviewHotkeys>`.
class PreviewHotkeys extends React.Component {
  constructor(props) {
    super(props);
    this.showNextPreview = this.showNextPreview.bind(this);
    this.showPreviousPreview = this.showPreviousPreview.bind(this);
    this.closePreview = this.closePreview.bind(this);
  }

  getCurrentPreviewIndex() {
    const { location, result } = this.props;
    const parsedHash = queryString.parse(location.hash);
    const results = result?.results || [];
    return results.findIndex((entity) => entity.id === parsedHash['preview:id']);
  }

  showNextPreview(event) {
    const results = this.props.result?.results || [];
    const currentIndex = this.getCurrentPreviewIndex();
    const nextEntity = results[currentIndex + 1];
    if (nextEntity && currentIndex >= 0) {
      event.preventDefault();
      this.showPreview(nextEntity);
    }
  }

  showPreviousPreview(event) {
    const results = this.props.result?.results || [];
    const currentIndex = this.getCurrentPreviewIndex();
    const previousEntity = results[currentIndex - 1];
    if (previousEntity && currentIndex >= 0) {
      event.preventDefault();
      this.showPreview(previousEntity);
    }
  }

  showPreview(entity) {
    const { navigate, location } = this.props;
    togglePreview(navigate, location, entity);
  }

  closePreview() {
    const { navigate, location } = this.props;
    togglePreview(navigate, location);
  }

  render() {
    const { children, groupLabel, intl } = this.props;
    const group = { group: groupLabel };
    return (
      <HotkeysContainer
        hotkeys={[
          {
            combo: 'j',
            label: intl.formatMessage(messages.next),
            onKeyDown: this.showNextPreview,
            ...group,
          },
          {
            combo: 'k',
            label: intl.formatMessage(messages.previous),
            onKeyDown: this.showPreviousPreview,
            ...group,
          },
          {
            combo: 'up',
            label: intl.formatMessage(messages.previous),
            onKeyDown: this.showPreviousPreview,
            ...group,
          },
          {
            combo: 'down',
            label: intl.formatMessage(messages.next),
            onKeyDown: this.showNextPreview,
            ...group,
          },
          {
            combo: 'esc',
            label: intl.formatMessage(messages.close_preview),
            onKeyDown: this.closePreview,
            ...group,
          },
        ]}
      >
        {children}
      </HotkeysContainer>
    );
  }
}

export default compose(withRouter, injectIntl)(PreviewHotkeys);
