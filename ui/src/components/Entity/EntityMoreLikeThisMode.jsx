import _ from 'lodash';
import { Component } from 'react';
import { defineMessages, injectIntl } from 'react-intl';
import { compose } from 'redux';
import { connect } from 'react-redux';
import queryString from 'query-string';

import withRouter from 'app/withRouter';
import { queryMoreLikeThis } from 'actions';
import { selectMoreLikeThisResult } from 'selectors';
import { ErrorSection } from 'components/common';
import EntityListTable from 'components/Entity/EntityListTable';
import FacetedResultList from 'components/EntitySearch/FacetedResultList';
import { entityMoreLikeThisQuery } from 'queries';
import ensureArray from 'util/ensureArray';

const messages = defineMessages({
  empty: {
    id: 'entity.more_like_this.empty',
    defaultMessage: 'There are no similar entities.',
  },
  group_label: {
    id: 'entity.more_like_this.group_label',
    defaultMessage: 'Similar entities preview',
  },
  entity_header: {
    id: 'entity.more_like_this.entity',
    defaultMessage: 'Similar entity',
  },
  summary: {
    id: 'entity.more_like_this.found_text',
    defaultMessage: `Found {resultCount}
      {resultCount, plural, one {similar document} other {similar documents}}
      from {datasetCount}
      {datasetCount, plural, one {dataset} other {datasets}}
    `,
  },
});

class EntityMoreLikeThisMode extends Component {
  render() {
    const { intl, query, result, results, previewId, navigate, location } =
      this.props;

    return (
      <FacetedResultList
        query={query}
        result={result}
        navigate={navigate}
        location={location}
        fetch={this.props.queryMoreLikeThis}
        defaultFacets={['schema', 'countries', 'languages']}
        additionalFields={['collection_id']}
        storageKey="entity:more_like_this"
        hideSidebarWhenEmpty
        previewGroupLabel={intl.formatMessage(messages.group_label)}
      >
        {result.total === 0 ? (
          <ErrorSection
            icon="search-text"
            title={intl.formatMessage(messages.empty)}
          />
        ) : (
          <EntityListTable
            className="EntityMoreLikeThisMode"
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
  const query = entityMoreLikeThisQuery(location, entity.id);
  const result = selectMoreLikeThisResult(state, query);
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
  connect(mapStateToProps, { queryMoreLikeThis }),
  injectIntl
)(EntityMoreLikeThisMode);
