import React, { Component } from 'react';
import { compose } from 'redux';
import { connect } from 'react-redux';
import { defineMessages, injectIntl } from 'react-intl';
import { Button } from '@blueprintjs/core';
import { Tooltip2 as Tooltip } from '@blueprintjs/popover2';

import { triggerEntityTranscribe } from 'actions';
import { showSuccessToast, showWarningToast } from 'app/toast';

const messages = defineMessages({
  transcribe: {
    id: 'entity.toolbar.transcribe',
    defaultMessage: 'Transcribe',
  },
  tooltip: {
    id: 'entity.toolbar.transcribe.tooltip',
    defaultMessage: 'Transcribe audio or video to text',
  },
  success: {
    id: 'entity.toolbar.transcribe.success',
    defaultMessage: 'Transcription has been queued.',
  },
});

class TranscribeButton extends Component {
  constructor(props) {
    super(props);
    this.state = { blocking: false };
    this.onTranscribe = this.onTranscribe.bind(this);
  }

  async onTranscribe() {
    const { entity, intl } = this.props;
    const { blocking } = this.state;
    if (blocking) return;
    this.setState({ blocking: true });
    try {
      await this.props.triggerEntityTranscribe(entity.id);
      showSuccessToast(intl.formatMessage(messages.success));
    } catch (e) {
      showWarningToast(e.message);
    } finally {
      this.setState({ blocking: false });
    }
  }

  render() {
    const { intl } = this.props;
    const { blocking } = this.state;

    return (
      <Tooltip content={intl.formatMessage(messages.tooltip)}>
        <Button
          icon="mobile-video"
          disabled={blocking}
          loading={blocking}
          onClick={this.onTranscribe}
          text={intl.formatMessage(messages.transcribe)}
        />
      </Tooltip>
    );
  }
}

export default compose(
  connect(null, { triggerEntityTranscribe }),
  injectIntl
)(TranscribeButton);
