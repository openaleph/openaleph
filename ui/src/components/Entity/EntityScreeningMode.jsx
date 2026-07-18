import _ from 'lodash';
import { Component } from 'react';
import { defineMessages, injectIntl } from 'react-intl';
import { compose } from 'redux';
import { connect } from 'react-redux';
import { Tag, Intent } from '@blueprintjs/core';
import queryString from 'query-string';

import withRouter from 'app/withRouter';
import { queryPercolate } from 'actions';
import { selectPercolateResult } from 'selectors';
import { ErrorSection, Topic } from 'components/common';
import EntityListTable from 'components/Entity/EntityListTable';
import FacetedResultList from 'components/EntitySearch/FacetedResultList';
import { entityPercolateQuery } from 'queries';
import ensureArray from 'util/ensureArray';

import './EntityScreeningMode.scss';

// Danger: sanctions, enforcement, crime – highest risk signals
const DANGER_TOPICS = new Set([
  'sanction', 'sanction.linked', 'sanction.counter',
  'debarment', 'wanted', 'asset.frozen',
  'export.control', 'export.control.linked',
  'crime', 'crime.fraud', 'crime.cyber', 'crime.fin', 'crime.env',
  'crime.theft', 'crime.war', 'crime.boss', 'crime.terror',
  'crime.traffick', 'crime.traffick.drug', 'crime.traffick.human',
  'forced.labor',
]);

// Warning: PEP, political exposure, risk indicators
const WARNING_TOPICS = new Set([
  'role.pep', 'role.pep.frmr', 'role.pep.intl', 'role.pep.natl',
  'role.rca', 'role.pol', 'role.judge', 'role.civil', 'role.diplo',
  'role.oligarch', 'role.spy',
  'export.risk', 'invest.risk',
  'reg.action', 'reg.warn',
  'mare.detained', 'mare.shadow', 'mare.sts',
  'corp.offshore', 'corp.shell', 'corp.disqual',
]);

function getTopicIntent(topic) {
  if (DANGER_TOPICS.has(topic)) return Intent.DANGER;
  if (WARNING_TOPICS.has(topic)) return Intent.WARNING;
  return Intent.NONE;
}

function renderTopicTags(entity) {
  const topics = entity.getProperty
    ? entity.getProperty('topics')
    : ensureArray(entity?.properties?.topics);
  if (!topics.length) return null;
  return (
    <span className="EntityScreeningMode__topics">
      {topics.map((topic) => (
        <Tag key={topic} minimal round intent={getTopicIntent(topic)}>
          <Topic.Name code={topic} />
        </Tag>
      ))}
    </span>
  );
}

const messages = defineMessages({
  empty: {
    id: 'entity.screening.empty',
    defaultMessage: 'No entity mentions found in this document.',
  },
  group_label: {
    id: 'entity.screening.group_label',
    defaultMessage: 'Screening results preview',
  },
  entity_header: {
    id: 'entity.screening.entity',
    defaultMessage: 'Mentioned entity',
  },
  summary: {
    id: 'entity.screening.found_text',
    defaultMessage: `Found {resultCount}
      {resultCount, plural, one {entity mention} other {entity mentions}}
      from {datasetCount}
      {datasetCount, plural, one {dataset} other {datasets}}
    `,
  },
});

class EntityScreeningMode extends Component {
  render() {
    const { intl, query, result, results, previewId, navigate, location } =
      this.props;

    return (
      <FacetedResultList
        query={query}
        result={result}
        navigate={navigate}
        location={location}
        fetch={this.props.queryPercolate}
        defaultFacets={['schema', 'countries']}
        additionalFields={['collection_id']}
        storageKey="entity:screening"
        hideSidebarWhenEmpty
        previewGroupLabel={intl.formatMessage(messages.group_label)}
      >
        {result.total === 0 ? (
          <ErrorSection
            icon="shield"
            title={intl.formatMessage(messages.empty)}
          />
        ) : (
          <EntityListTable
            className="EntityScreeningMode"
            result={result}
            results={results}
            previewId={previewId}
            entityHeader={messages.entity_header}
            summary={messages.summary}
            renderAccent={renderTopicTags}
          />
        )}
      </FacetedResultList>
    );
  }
}

const mapStateToProps = (state, ownProps) => {
  const { entity, location } = ownProps;
  const query = entityPercolateQuery(location, entity.id);
  const result = selectPercolateResult(state, query);
  const results = _.uniqBy(ensureArray(result.results), 'id');

  const parsedHash = queryString.parse(location.hash);

  return {
    query,
    result,
    results,
    previewId: parsedHash['preview:id'],
    selectedIndex: +parsedHash.selectedIndex,
  };
};

export default compose(
  withRouter,
  connect(mapStateToProps, { queryPercolate }),
  injectIntl
)(EntityScreeningMode);
