import _ from 'lodash';
import React from 'react';
import { defineMessages, injectIntl, FormattedMessage } from 'react-intl';
import { compose } from 'redux';
import { connect } from 'react-redux';
import { Button } from '@blueprintjs/core';
import queryString from 'query-string';
import c from 'classnames';

import withRouter from 'app/withRouter';
import { selectModel, selectNearbyResult } from 'selectors';
import {
  Collection,
  Entity,
  ErrorSection,
  HotkeysContainer,
  Property,
  QueryInfiniteLoad,
  Schema,
  Skeleton,
} from 'components/common';
import EntityProperties from 'components/Entity/EntityProperties';
import ensureArray from 'util/ensureArray';
import togglePreview from 'util/togglePreview';
import { queryNearby } from 'actions/index';
import EntityActionBar from './EntityActionBar';

const messages = defineMessages({
  no_relationships: {
    id: 'entity.references.no_relationships',
    defaultMessage: 'This entity does not have any relationships.',
  },
  no_results: {
    id: 'entity.references.no_results',
    defaultMessage: 'No {schema} match this search.',
  },
  no_results_default: {
    id: 'entity.references.no_results_default',
    defaultMessage: 'No entities match this search.',
  },
  search_placeholder: {
    id: 'entity.references.search.placeholder',
    defaultMessage: 'Search in {schema}',
  },
  search_placeholder_default: {
    id: 'entity.references.search.placeholder_default',
    defaultMessage: 'Search entities',
  },
  group_label: {
    id: 'entity.nearby.group_label',
    defaultMessage: 'Nearby entities preview',
  },
  next_preview: {
    id: 'entity.nearby.next_preview',
    defaultMessage: 'Preview next nearby entity',
  },
  previous_preview: {
    id: 'entity.nearby.previous_preview',
    defaultMessage: 'Preview previous nearby entity',
  },
  close_preview: {
    id: 'entity.nearby.close_preview',
    defaultMessage: 'Close preview',
  },
});

class EntityNearbyMode extends React.Component {
  constructor(props) {
    super(props);
    this.onSearchSubmit = this.onSearchSubmit.bind(this);
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

  onSearchSubmit(queryText) {
    const { query, navigate, location } = this.props;
    const newQuery = query.set('q', queryText);
    navigate({
      pathname: location.pathname,
      search: newQuery.toLocation(),
      hash: location.hash,
    });
  }

  onExpand(entity) {
    const { expandedId, parsedHash, navigate, location } = this.props;
    parsedHash.expand = expandedId === entity.id ? undefined : entity.id;
    navigate(
      {
        pathname: location.pathname,
        search: location.search,
        hash: queryString.stringify(parsedHash),
      },
      { replace: true }
    );
  }

  renderCell(prop, entity) {
    const propVal = (
      <Property.Values
        prop={prop}
        values={entity.getProperty(prop.name)}
        translitLookup={entity.latinized}
        preview
      />
    );
    if (prop.name === 'full') {
      return (
        <td key={prop.name} className="entity">
          <Entity.Link entity={entity} preview>
            <Schema.Icon schema={entity.schema} className="left-icon" />
            {propVal}
          </Entity.Link>
        </td>
      );
    }
    return (
      <td key={prop.name} className={prop.type.name}>
        {propVal}
      </td>
    );
  }

  renderRow(columns, entity, model) {
    const { expandedId, previewId, hideCollection } = this.props;
    const isExpanded = entity.id === expandedId;
    const expandIcon = isExpanded ? 'chevron-up' : 'chevron-down';

    const mainRow = (
      <tr
        key={entity.id}
        className={c('nowrap', {
          prefix: isExpanded,
          active: previewId === entity.id,
        })}
      >
        <td className="distance" style={{ width: 'auto', minWidth: '50px' }}>
          {parseFloat(entity._sort[0]).toFixed(2)} km
        </td>
        <td className="expand">
          <Button
            onClick={() => this.onExpand(entity)}
            small
            minimal
            icon={expandIcon}
          />
        </td>
        {columns.map((prop) => this.renderCell(prop, model.getEntity(entity)))}
        {!hideCollection && (
          <td key={entity.collection?.id}>
            <Collection.Link collection={entity.collection} />
          </td>
        )}
      </tr>
    );
    if (!isExpanded) {
      return mainRow;
    }
    const colSpan = hideCollection ? columns.length : columns.length + 1;
    return [
      mainRow,
      <tr key={`${entity.id}-expanded`}>
        <td />
        <td colSpan={colSpan}>
          <EntityProperties
            entity={model.getEntity(entity)}
            showMetadata={false}
          />
        </td>
      </tr>,
    ];
  }

  renderSkeleton(columns, idx) {
    const { hideCollection } = this.props;
    return (
      <tr key={idx} className="nowrap skeleton">
        {columns.map((c) => (
          <td key={c}>
            <Skeleton.Text type="span" length={10} />
          </td>
        ))}
        {!hideCollection && (
          <td key="collection">
            <Skeleton.Text type="span" length={20} />
          </td>
        )}
      </tr>
    );
  }

  render() {
    const { intl, query, result, results, model, hideCollection } = this.props;
    const schema = model.getSchema('Address');

    if (!result) {
      return (
        <ErrorSection
          icon="graph"
          title={intl.formatMessage(messages.no_relationships)}
        />
      );
    }
    const columns = schema.getFeaturedProperties();
    const schemaLabel = schema.plural.toLowerCase();
    const placeholder = intl.formatMessage(messages.search_placeholder, {
      schema: schemaLabel,
    });
    const skeletonItems = [...Array(15).keys()];
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
        <section className="EntityReferencesTable">
          <EntityActionBar
            query={query}
            onSearchSubmit={this.onSearchSubmit}
            searchPlaceholder={placeholder}
          ></EntityActionBar>
          {result.total !== 0 && (
            <>
              <table className="data-table references-data-table">
                <thead>
                  <tr>
                    <th key="distance" />
                    <th key="expand" />
                    {columns.map((prop) => (
                      <th key={prop.name} className={prop.type}>
                        <Property.Name prop={prop} />
                      </th>
                    ))}
                    {!hideCollection && (
                      <th>
                        <FormattedMessage
                          id="xref.match_collection"
                          defaultMessage="Dataset"
                        />
                      </th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {results.map((entity) =>
                    this.renderRow(columns, entity, model)
                  )}
                  {result.isPending &&
                    skeletonItems.map((idx) =>
                      this.renderSkeleton(columns, idx)
                    )}
                </tbody>
              </table>
              <QueryInfiniteLoad
                query={query}
                result={result}
                fetch={this.props.queryNearby}
              />
            </>
          )}
          {result.total === 0 && (
            <ErrorSection
              icon={
                <Schema.Icon schema={schema} className="left-icon" size={60} />
              }
              title={intl.formatMessage(messages.no_results, {
                schema: schemaLabel,
              })}
            />
          )}
        </section>
      </HotkeysContainer>
    );
  }
}

const mapStateToProps = (state, ownProps) => {
  const { location, query } = ownProps;
  const parsedHash = queryString.parse(location.hash);
  const result = selectNearbyResult(state, query);
  const results = _.uniqBy(ensureArray(result.results), 'id');
  return {
    model: selectModel(state),
    parsedHash,
    expandedId: parsedHash.expand,
    previewId: parsedHash['preview:id'],
    result,
    results,
  };
};

export default compose(
  withRouter,
  connect(mapStateToProps, { queryNearby }),
  injectIntl
)(EntityNearbyMode);
