import { Component } from 'react';
import { defineMessages, FormattedMessage, injectIntl } from 'react-intl';
import { connect } from 'react-redux';
import { Callout } from '@blueprintjs/core';
import queryString from 'query-string';

import withRouter from 'app/withRouter';
import { queryMoreLikeThis } from 'actions';
import { selectMoreLikeThisResult } from 'selectors';
import {
  ErrorSection,
  QueryInfiniteLoad,
  Entity,
  Collection,
  Skeleton,
} from 'components/common';
import { entityMoreLikeThisQuery } from 'queries';

const messages = defineMessages({
  empty: {
    id: 'entity.more_like_this.empty',
    defaultMessage: 'There are no similar entities.',
  },
});

class EntityMoreLikeThisMode extends Component {
  renderSummary() {
    const { result } = this.props;
    if (result.total === undefined || result.total === 0) {
      return null;
    }

    return (
      <Callout icon={null} intent="primary">
        <FormattedMessage
          id="entity.more_like_this.found_text"
          defaultMessage={`Found {resultCount}
            {resultCount, plural, one {similar document} other {similar documents}}
            from {datasetCount}
            {datasetCount, plural, one {dataset} other {datasets}}
          `}
          values={{
            resultCount: result.total,
            datasetCount: result.facets.collection_id.total,
          }}
        />
      </Callout>
    );
  }

  renderHeader() {
    return (
      <thead>
        <tr>
          <th>
            <span className="value">
              <FormattedMessage
                id="entity.more_like_this.entity"
                defaultMessage="Similar entity"
              />
            </span>
          </th>
          <th className="collection">
            <span className="value">
              <FormattedMessage
                id="xref.match_collection"
                defaultMessage="Dataset"
              />
            </span>
          </th>
        </tr>
      </thead>
    );
  }

  renderSkeleton(idx) {
    return (
      <tr key={idx}>
        <td className="entity bordered">
          <Entity.Link isPending />
        </td>
        <td className="collection">
          <Skeleton.Text type="span" length={10} />
        </td>
      </tr>
    );
  }

  renderRow(entity) {
    return (
      <tr key={entity.id}>
        <td className="entity bordered">
          <Entity.Link entity={entity} />
        </td>
        <td className="collection">
          <Collection.Link collection={entity.collection} icon />
        </td>
      </tr>
    );
  }

  render() {
    const { intl, query, result } = this.props;
    const skeletonItems = [...Array(10).keys()];

    if (result.total === 0) {
      return (
        <ErrorSection
          icon="search-text"
          title={intl.formatMessage(messages.empty)}
        />
      );
    }

    return (
      <div className="EntityMoreLikeThisMode">
        {this.renderSummary()}
        <table className="data-table">
          {this.renderHeader()}
          <tbody>
            {result.results?.map((entity) => this.renderRow(entity))}
            {result.isPending &&
              skeletonItems.map((idx) => this.renderSkeleton(idx))}
          </tbody>
        </table>
        <QueryInfiniteLoad
          query={query}
          result={result}
          fetch={this.props.queryMoreLikeThis}
        />
      </div>
    );
  }
}

const mapStateToProps = (state, ownProps) => {
  const { entity, location } = ownProps;
  const query = entityMoreLikeThisQuery(location, entity.id);
  const result = selectMoreLikeThisResult(state, query);

  const parsedHash = queryString.parse(location.hash);

  return { query, result, selectedIndex: +parsedHash.selectedIndex };
};

EntityMoreLikeThisMode = connect(mapStateToProps, {
  queryMoreLikeThis,
})(EntityMoreLikeThisMode);
EntityMoreLikeThisMode = withRouter(EntityMoreLikeThisMode);
EntityMoreLikeThisMode = injectIntl(EntityMoreLikeThisMode);
export default EntityMoreLikeThisMode;
