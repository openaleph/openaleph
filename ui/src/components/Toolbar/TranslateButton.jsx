import React, { Component } from 'react';
import { compose } from 'redux';
import { connect } from 'react-redux';
import { defineMessages, injectIntl } from 'react-intl';
import { Button } from '@blueprintjs/core';
import { Tooltip2 as Tooltip } from '@blueprintjs/popover2';

import { triggerEntityTranslate } from 'actions';
import { showSuccessToast, showWarningToast } from 'app/toast';

const messages = defineMessages({
  translate: {
    id: 'entity.toolbar.translate',
    defaultMessage: 'Translate',
  },
  tooltip: {
    id: 'entity.toolbar.translate.tooltip',
    defaultMessage: 'Translate entity text',
  },
  processing: {
    id: 'entity.toolbar.translate.processing',
    defaultMessage: 'Translation in progress',
  },
  success: {
    id: 'entity.toolbar.translate.success',
    defaultMessage: 'Translation has been queued.',
  },
});

class TranslateButton extends Component {
  constructor(props) {
    super(props);
    this.state = { blocking: false, processing: false };
    this.onTranslate = this.onTranslate.bind(this);
  }

  async onTranslate() {
    const { entity, intl } = this.props;
    const { blocking } = this.state;
    if (blocking) return;
    this.setState({ blocking: true });
    try {
      await this.props.triggerEntityTranslate(entity.id);
      showSuccessToast(intl.formatMessage(messages.success));
      this.setState({ processing: true });
    } catch (e) {
      showWarningToast(e.message);
    } finally {
      this.setState({ blocking: false });
    }
  }

  render() {
    const { entity, intl } = this.props;
    const { blocking, processing } = this.state;
    const isProcessing = processing || entity?.processing_status?.translate;
    const tooltipMessage = isProcessing
      ? intl.formatMessage(messages.processing)
      : intl.formatMessage(messages.tooltip);

    return (
      <Tooltip content={tooltipMessage}>
        <Button
          icon="translate"
          disabled={blocking || isProcessing}
          loading={blocking}
          onClick={this.onTranslate}
          text={intl.formatMessage(messages.translate)}
        />
      </Tooltip>
    );
  }
}

export default compose(
  connect(null, { triggerEntityTranslate }),
  injectIntl
)(TranslateButton);
