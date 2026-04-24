import _ from 'lodash';
import { Component } from 'react';
import { defineMessages, FormattedMessage, injectIntl } from 'react-intl';
import { compose } from 'redux';
import { connect } from 'react-redux';
import { Callout } from '@blueprintjs/core';
import queryString from 'query-string';
import c from 'classnames';

import withRouter from 'app/withRouter';
import { queryMentions } from 'actions';
import { selectMentionsResult } from 'selectors';
import {
  ErrorSection,
  FacetedLayout,
  HotkeysContainer,
  QueryInfiniteLoad,
  Entity,
  Collection,
  Schema,
  Skeleton,
  SearchHighlight,
} from 'components/common';
import { entityMentionsQuery } from 'queries';
import ensureArray from 'util/ensureArray';
import togglePreview from 'util/togglePreview';

const messages = defineMessages({
  empty: {
    id: 'entity.mentions.empty',
    defaultMessage: 'No documents mention this entity.',
  },
  group_label: {
    id: 'entity.mentions.group_label',
    defaultMessage: 'Mentions preview',
  },
  next_preview: {
    id: 'entity.mentions.next_preview',
    defaultMessage: 'Preview next document',
  },
  previous_preview: {
    id: 'entity.mentions.previous_preview',
    defaultMessage: 'Preview previous document',
  },
  close_preview: {
    id: 'entity.mentions.close_preview',
    defaultMessage: 'Close preview',
  },
});

class EntityMentionsMode extends Component {
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
          id="entity.mentions.found_text"
          defaultMessage={`Found {resultCount}
            {resultCount, plural, one {document} other {documents}}
            mentioning this entity from {datasetCount}
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
                id="entity.mentions.document"
                defaultMessage="Document"
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
            <Entity.Link entity={entity} preview>
              <Schema.Icon schema={entity.schema} className="left-icon" />
              {entity.getCaption()}
            </Entity.Link>
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
          defaultFacets={['schema', 'countries']}
          additionalFields={['collection_id']}
          storageKey="entity:mentions"
          hideSidebarWhenEmpty
        >
          <div className="EntityMentionsMode">
            {result.total === 0 ? (
              <ErrorSection
                icon="document"
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
                  fetch={this.props.queryMentions}
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
