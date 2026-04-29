import _ from 'lodash';
import { Component } from 'react';
import { defineMessages, FormattedMessage, injectIntl } from 'react-intl';
import { compose } from 'redux';
import { connect } from 'react-redux';
import { Callout } from '@blueprintjs/core';
import queryString from 'query-string';
import c from 'classnames';

import withRouter from 'app/withRouter';
import { queryMoreLikeThis } from 'actions';
import { selectMoreLikeThisResult } from 'selectors';
import {
  ErrorSection,
  FacetedLayout,
  HotkeysContainer,
  QueryInfiniteLoad,
  Entity,
  Collection,
  Skeleton,
  SearchHighlight,
} from 'components/common';
import { entityMoreLikeThisQuery } from 'queries';
import ensureArray from 'util/ensureArray';
import togglePreview from 'util/togglePreview';

const messages = defineMessages({
  empty: {
    id: 'entity.more_like_this.empty',
    defaultMessage: 'There are no similar entities.',
  },
  group_label: {
    id: 'entity.more_like_this.group_label',
    defaultMessage: 'Similar entities preview',
  },
  next_preview: {
    id: 'entity.more_like_this.next_preview',
    defaultMessage: 'Preview next similar entity',
  },
  previous_preview: {
    id: 'entity.more_like_this.previous_preview',
    defaultMessage: 'Preview previous similar entity',
  },
  close_preview: {
    id: 'entity.more_like_this.close_preview',
    defaultMessage: 'Close preview',
  },
});

class EntityMoreLikeThisMode extends Component {
  constructor(props) {
    super(props);
    this.getCurrentPreviewIndex = this.getCurrentPreviewIndex.bind(this);
    this.showNextPreview = this.showNextPreview.bind(this);
    this.showPreviousPreview = this.showPreviousPreview.bind(this);
    this.showPreview = this.showPreview.bind(this);
    this.closePreview = this.closePreview.bind(this);
  }

  getCurrentPreviewIndex() {
    const { previewId, results } = this.props;
    return results.findIndex((entity) => entity.id === previewId);
  }

  showNextPreview(event) {
    const { results } = this.props;
    const currentSelectionIndex = this.getCurrentPreviewIndex();
    const nextEntity = results[1 + currentSelectionIndex];

    if (nextEntity && currentSelectionIndex >= 0) {
      event.preventDefault();
      this.showPreview(nextEntity);
    }
  }

  showPreviousPreview(event) {
    const { results } = this.props;
    const currentSelectionIndex = this.getCurrentPreviewIndex();
    const previousEntity = results[currentSelectionIndex - 1];

    if (previousEntity && currentSelectionIndex >= 0) {
      event.preventDefault();
      this.showPreview(previousEntity);
    }
  }

  showPreview(entity) {
    const { navigate, location } = this.props;
    togglePreview(navigate, location, entity);
  }

  closePreview() {
    const { navigate, location } = this.props;
    togglePreview(navigate, location);
  }

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
            datasetCount: result.facets?.collection_id?.total ?? 0,
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
    const { previewId } = this.props;
    return (
      <>
        <tr
          key={entity.id}
          className={c({ active: previewId === entity.id })}
        >
          <td className="entity bordered">
            <Entity.Link entity={entity} preview />
          </td>
          <td className="collection">
            <Collection.Link collection={entity.collection} icon />
          </td>
        </tr>
        {entity.highlight ? (
          <tr key={`${entity.id}-hl`}>
            <td colSpan="100%" className="highlights">
              <SearchHighlight highlight={entity.highlight} />
            </td>
          </tr>
        ) : null}
      </>
    );
  }

  render() {
    const { intl, query, result, results, navigate, location } = this.props;
    const skeletonItems = [...Array(10).keys()];

    const hotkeysGroupLabel = {
      group: intl.formatMessage(messages.group_label),
    };

    return (
      <HotkeysContainer
        hotkeys={[
          {
            combo: 'j',
            label: intl.formatMessage(messages.next_preview),
            onKeyDown: this.showNextPreview,
            ...hotkeysGroupLabel,
          },
          {
            combo: 'k',
            label: intl.formatMessage(messages.previous_preview),
            onKeyDown: this.showPreviousPreview,
            ...hotkeysGroupLabel,
          },
          {
            combo: 'up',
            label: intl.formatMessage(messages.previous_preview),
            onKeyDown: this.showPreviousPreview,
            ...hotkeysGroupLabel,
          },
          {
            combo: 'down',
            label: intl.formatMessage(messages.next_preview),
            onKeyDown: this.showNextPreview,
            ...hotkeysGroupLabel,
          },
          {
            combo: 'esc',
            label: intl.formatMessage(messages.close_preview),
            onKeyDown: this.closePreview,
            ...hotkeysGroupLabel,
          },
        ]}
      >
        <FacetedLayout
          query={query}
          result={result}
          navigate={navigate}
          location={location}
          defaultFacets={['schema', 'countries', 'languages']}
          additionalFields={['collection_id']}
          storageKey="entity:more_like_this"
          hideSidebarWhenEmpty
        >
          <div className="EntityMoreLikeThisMode">
            {result.total === 0 ? (
              <ErrorSection
                icon="search-text"
                title={intl.formatMessage(messages.empty)}
              />
            ) : (
              <>
                {this.renderSummary()}
                <table className="data-table">
                  {this.renderHeader()}
                  <tbody>
                    {results.map((entity) => this.renderRow(entity))}
                    {result.isPending &&
                      skeletonItems.map((idx) => this.renderSkeleton(idx))}
                  </tbody>
                </table>
                <QueryInfiniteLoad
                  query={query}
                  result={result}
                  fetch={this.props.queryMoreLikeThis}
                />
              </>
            )}
          </div>
        </FacetedLayout>
      </HotkeysContainer>
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
