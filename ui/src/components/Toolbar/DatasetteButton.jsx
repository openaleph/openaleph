import React, { Component } from 'react';
import { Button, FormGroup } from '@blueprintjs/core';
import { Popover2 as Popover } from '@blueprintjs/popover2';
import { defineMessages, injectIntl, FormattedMessage } from 'react-intl';

const messages = defineMessages({
  label: {
    id: 'document.datasette',
    defaultMessage: 'Explore data',
  },
  skiprows_label: {
    id: 'document.datasette.skiprows',
    defaultMessage: 'Skip first N rows',
  },
  generic_headers_label: {
    id: 'document.datasette.generic_headers',
    defaultMessage: 'Add generic headers (col1, col2, …)',
  },
  open: {
    id: 'document.datasette.open',
    defaultMessage: 'Open',
  },
});

class DatasetteButton extends Component {
  constructor(props) {
    super(props);
    this.state = { skiprows: 0, genericHeaders: false };
    this.onOpen = this.onOpen.bind(this);
  }

  onOpen() {
    const { document } = this.props;
    const { skiprows, genericHeaders } = this.state;
    const params = new URLSearchParams({ csv: document.links.csv });
    if (genericHeaders) {
      params.set('skiprows', -1);
    } else if (skiprows > 0) {
      params.set('skiprows', skiprows);
    }
    window.open(`/datasette-lite/index.html?${params}#/main/table`, '_blank', 'noopener,noreferrer');
  }

  render() {
    const { intl } = this.props;
    const { skiprows, genericHeaders } = this.state;

    const content = (
      <div style={{ padding: '12px', minWidth: '220px' }}>
        <FormGroup label={intl.formatMessage(messages.skiprows_label)}>
          <input
            className="bp4-input bp4-fill"
            type="number"
            min={0}
            value={skiprows}
            disabled={genericHeaders}
            onChange={(e) => this.setState({ skiprows: parseInt(e.target.value) || 0 })}
          />
        </FormGroup>
        <FormGroup>
          <label className="bp4-control bp4-checkbox">
            <input
              type="checkbox"
              checked={genericHeaders}
              onChange={(e) => this.setState({ genericHeaders: e.target.checked })}
            />
            <span className="bp4-control-indicator" />
            {intl.formatMessage(messages.generic_headers_label)}
          </label>
        </FormGroup>
        <Button fill intent="primary" onClick={this.onOpen}>
          <FormattedMessage {...messages.open} />
        </Button>
      </div>
    );

    return (
      <Popover content={content} placement="bottom-start">
        <Button icon="database" text={intl.formatMessage(messages.label)} />
      </Popover>
    );
  }
}

export default injectIntl(DatasetteButton);
