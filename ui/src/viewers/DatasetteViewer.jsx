import React, { Component } from 'react';
import { Button, FormGroup } from '@blueprintjs/core';
import { defineMessages, injectIntl, FormattedMessage } from 'react-intl';

import './DatasetteViewer.scss';

const messages = defineMessages({
  skiprows_label: {
    id: 'document.datasette.skiprows',
    defaultMessage: 'Skip rows (if headers below first row)',
  },
  generic_headers_label: {
    id: 'document.datasette.generic_headers',
    defaultMessage: 'Add generic headers (if file has data in first row)',
  },
  open: {
    id: 'document.datasette.open',
    defaultMessage: 'Load',
  },
});

class DatasetteViewer extends Component {
  constructor(props) {
    super(props);
    this.state = { skiprows: 0, genericHeaders: false, src: null };
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
    this.setState({ src: `/datasette-lite/index.html?${params}#/main/table` });
  }

  render() {
    const { intl } = this.props;
    const { skiprows, genericHeaders, src } = this.state;

    if (src) {
      return (
        <iframe
          className="DatasetteViewer__frame"
          src={src}
          title="Datasette"
        />
      );
    }

    return (
      <div className="DatasetteViewer__settings">
        <FormGroup label={intl.formatMessage(messages.skiprows_label)}>
          <input
            className="bp4-input"
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
        <Button intent="primary" onClick={this.onOpen}>
          <FormattedMessage {...messages.open} />
        </Button>
      </div>
    );
  }
}

export default injectIntl(DatasetteViewer);
