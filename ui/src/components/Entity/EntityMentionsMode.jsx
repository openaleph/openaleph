import _ from 'lodash';
import { Component } from 'react';
import { defineMessages, injectIntl } from 'react-intl';
import { compose } from 'redux';
import { connect } from 'react-redux';
import queryString from 'query-string';

import withRouter from 'app/withRouter';
import { queryMentions } from 'actions';
import { selectMentionsResult } from 'selectors';
import { ErrorSection } from 'components/common';
import EntityListTable from 'components/Entity/EntityListTable';
import FacetedResultList from 'components/EntitySearch/FacetedResultList';
import { entityMentionsQuery } from 'queries';
import ensureArray from 'util/ensureArray';

const messages = defineMessages({
  empty: {
    id: 'entity.mentions.empty',
    defaultMessage: 'No documents mention this entity.',
  },
  group_label: {
    id: 'entity.mentions.group_label',
    defaultMessage: 'Mentions preview',
  },
  entity_header: {
    id: 'entity.mentions.document',
    defaultMessage: 'Document',
  },
  summary: {
    id: 'entity.mentions.found_text',
    defaultMessage: `Found {resultCount}
      {resultCount, plural, one {document} other {documents}}
      mentioning this entity from {datasetCount}
      {datasetCount, plural, one {dataset} other {datasets}}
    `,
  },
});

class EntityMentionsMode extends Component {
  render() {
    const { intl, query, result, results, previewId, navigate, location } =
      this.props;

    return (
      <FacetedResultList
        query={query}
        result={result}
        navigate={navigate}
        location={location}
        fetch={this.props.queryMentions}
        defaultFacets={['schema', 'countries']}
        additionalFields={['collection_id']}
        storageKey="entity:mentions"
        hideSidebarWhenEmpty
        previewGroupLabel={intl.formatMessage(messages.group_label)}
      >
        {result.total === 0 ? (
          <ErrorSection
            icon="document"
            title={intl.formatMessage(messages.empty)}
          />
        ) : (
          <EntityListTable
            className="EntityMentionsMode"
            result={result}
            results={results}
            previewId={previewId}
            entityHeader={messages.entity_header}
            summary={messages.summary}
          />
        )}
      </FacetedResultList>
    );
  }
}

const mapStateToProps = (state, ownProps) => {
  const { entity, location } = ownProps;
  const query = entityMentionsQuery(location, entity.id);
  const result = selectMentionsResult(state, query);
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
  connect(mapStateToProps, { queryMentions }),
  injectIntl
)(EntityMentionsMode);
