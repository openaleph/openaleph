import React, { Component } from 'react';
import { compose } from 'redux';
import { connect } from 'react-redux';
import { defineMessages, injectIntl } from 'react-intl';
import { Button, Menu, MenuItem } from '@blueprintjs/core';
import { Popover2 as Popover } from '@blueprintjs/popover2';
import { Tooltip2 as Tooltip } from '@blueprintjs/popover2';

import { triggerEntityTranslate } from 'actions';
import { selectModel } from 'selectors';
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
  source_language: {
    id: 'entity.toolbar.translate.source_language',
    defaultMessage: 'Translate from…',
  },
  translate_from: {
    id: 'entity.toolbar.translate.translate_from',
    defaultMessage: 'Translate from: {language}',
  },
  auto_detect: {
    id: 'entity.toolbar.translate.auto_detect',
    defaultMessage: 'Auto-detect language',
  },
});

class TranslateButton extends Component {
  constructor(props) {
    super(props);
    this.state = { blocking: false, processing: false };
    this.onTranslate = this.onTranslate.bind(this);
  }

  async onTranslate(sourceLanguage) {
    const { entity, intl } = this.props;
    const { blocking } = this.state;
    if (blocking) return;
    this.setState({ blocking: true });
    try {
      await this.props.triggerEntityTranslate(
        entity.id,
        sourceLanguage || undefined
      );
      showSuccessToast(intl.formatMessage(messages.success));
      this.setState({ processing: true });
    } catch (e) {
      showWarningToast(e.message);
    } finally {
      this.setState({ blocking: false });
    }
  }

  render() {
    const { entity, intl, languageValues } = this.props;
    const { blocking, processing } = this.state;
    const isProcessing = processing || entity?.processing_status?.translate;
    const collectionLanguages = entity?.collection?.languages || [];
    const detectedLanguages = entity?.getProperty?.('detectedLanguage') || [];
    const languages = [
      ...new Set([...detectedLanguages, ...collectionLanguages]),
    ];

    let menu = null;
    if (languages.length > 0) {
      menu = (
        <Menu>
          <MenuItem
            text={intl.formatMessage(messages.auto_detect)}
            onClick={() => this.onTranslate(null)}
          />
          {languages.map((code) => {
            const label = languageValues?.get?.(code) || code;
            return (
              <MenuItem
                key={code}
                text={intl.formatMessage(messages.translate_from, { language: label })}
                onClick={() => this.onTranslate(code)}
              />
            );
          })}
        </Menu>
      );

      return (
        <Popover
          content={menu}
          placement="bottom-start"
          disabled={blocking || isProcessing}
        >
          <Tooltip
            content={
              isProcessing
                ? intl.formatMessage(messages.processing)
                : intl.formatMessage(messages.source_language)
            }
          >
            <Button
              icon="translate"
              disabled={blocking || isProcessing}
              loading={blocking}
              text={intl.formatMessage(messages.translate)}
              rightIcon="caret-down"
            />
          </Tooltip>
        </Popover>
      );
    }

    const tooltipMessage = isProcessing
      ? intl.formatMessage(messages.processing)
      : intl.formatMessage(messages.tooltip);

    return (
      <Tooltip content={tooltipMessage}>
        <Button
          icon="translate"
          disabled={blocking || isProcessing}
          loading={blocking}
          onClick={() => this.onTranslate(null)}
          text={intl.formatMessage(messages.translate)}
        />
      </Tooltip>
    );
  }
}

const mapStateToProps = (state) => {
  const model = selectModel(state);
  return {
    languageValues: model?.types?.language?.values || {},
  };
};

export default compose(
  connect(mapStateToProps, { triggerEntityTranslate }),
  injectIntl
)(TranslateButton);
