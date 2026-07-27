import React, { Component } from 'react';
import { FormattedDate, FormattedMessage } from 'react-intl';
import { connect } from 'react-redux';
import { Callout, Spinner } from '@blueprintjs/core';

import { fetchCanonicalStatements } from 'actions';
import { selectCanonicalStatements } from 'selectors';
import { Entity, Collection } from 'components/common';

import './ProfileProvenanceMode.scss';

class ProfileProvenanceMode extends Component {
  componentDidMount() {
    this.fetchIfNeeded();
  }

  componentDidUpdate() {
    this.fetchIfNeeded();
  }

  fetchIfNeeded() {
    const { canonical, statementsResult } = this.props;
    if (canonical?.id && statementsResult.shouldLoad) {
      this.props.fetchCanonicalStatements({ id: canonical.id });
    }
  }

  renderValue(stmt) {
    if (typeof stmt.value === 'object' && stmt.value?.id) {
      return <Entity.Link entity={stmt.value} icon />;
    }
    if (stmt.prop_type === 'url') {
      return (
        <a href={stmt.value} target="_blank" rel="noopener noreferrer">
          {stmt.value}
        </a>
      );
    }
    return stmt.value;
  }

  renderRow(stmt) {
    return (
      <tr key={stmt.id}>
        <td className="prop">
          <code>
            <span className="text-muted">{stmt.schema}:</span>
            {stmt.prop}
          </code>
        </td>
        <td className="value">{this.renderValue(stmt)}</td>
        <td className="lang">{stmt.lang || ''}</td>
        <td className="dataset">
          {stmt.dataset && <Collection.Link collection={stmt.dataset} icon />}
        </td>
        <td className="first-seen">
          {stmt.first_seen && (
            <FormattedDate
              value={stmt.first_seen}
              year="numeric"
              month="2-digit"
              day="2-digit"
            />
          )}
        </td>
      </tr>
    );
  }

  render() {
    const { statementsResult } = this.props;

    if (statementsResult.isPending) {
      return <Spinner />;
    }

    const results = statementsResult.results || [];

    if (results.length === 0) {
      return (
        <Callout icon="document-open" intent="primary">
          <FormattedMessage
            id="profile.provenance.empty"
            defaultMessage="No data lineage statements available for this profile."
          />
        </Callout>
      );
    }

    return (
      <div className="ProfileProvenanceMode">
        <table className="data-table">
          <thead>
            <tr>
              <th>
                <FormattedMessage
                  id="profile.provenance.prop"
                  defaultMessage="Property"
                />
              </th>
              <th>
                <FormattedMessage
                  id="profile.provenance.value"
                  defaultMessage="Value"
                />
              </th>
              <th>
                <FormattedMessage
                  id="profile.provenance.lang"
                  defaultMessage="Lang"
                />
              </th>
              <th>
                <FormattedMessage
                  id="profile.provenance.dataset"
                  defaultMessage="Source dataset"
                />
              </th>
              <th>
                <FormattedMessage
                  id="profile.provenance.first_seen"
                  defaultMessage="First seen"
                />
              </th>
            </tr>
          </thead>
          <tbody>
            {results.map((stmt) => this.renderRow(stmt))}
          </tbody>
        </table>
      </div>
    );
  }
}

const mapStateToProps = (state, ownProps) => {
  const { canonical } = ownProps;
  return {
    statementsResult: selectCanonicalStatements(state, canonical?.id),
  };
};

export default connect(mapStateToProps, { fetchCanonicalStatements })(
  ProfileProvenanceMode
);
