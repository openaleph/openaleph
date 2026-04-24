import React from 'react';
import _ from 'lodash';
import queryString from 'query-string';
import { defineMessages, injectIntl } from 'react-intl';
import { Button } from '@blueprintjs/core';
import { compose } from 'redux';
import { connect } from 'react-redux';

import withRouter from 'app/withRouter';
import { triggerQueryExport } from 'src/actions';
import { getSearchConfig } from 'app/storage';
import { getGroupField } from 'components/SearchField/util';
import {
  getColumnsFromHash,
  getDefaultColumns,
  setColumnsInHash,
} from 'util/columnHash';
import {
  ErrorSection,
  FacetedLayout,
  HotkeysContainer,
} from 'components/common';
import EntitySearch from 'components/EntitySearch/EntitySearch';
import SearchActionBar from 'components/common/SearchActionBar';
import SearchFieldSelect from 'components/SearchField/SearchFieldSelect';
import togglePreview from 'util/togglePreview';
import { selectModel } from 'selectors';

import './FacetedEntitySearch.scss';

const defaultFacets = [
  'dates',
  'schema',
  'countries',
  'languages',
  'emails',
  'phones',
  'names',
  'addresses',
  'tags',
];

const messages = defineMessages({
  no_results_title: {
    id: 'search.no_results_title',
    defaultMessage: 'No search results',
  },
  no_results_description: {
    id: 'search.no_results_description',
    defaultMessage: 'Try making your search more general',
  },
  group_label: {
    id: 'hotkeys.search.group_label',
    defaultMessage: 'Search preview',
  },
  next: {
    id: 'hotkeys.search.unsure',
    defaultMessage: 'Preview next result',
  },
  previous: {
    id: 'hotkeys.search.different',
    defaultMessage: 'Preview previous result',
  },
  close_preview: {
    id: 'hotkeys.search.close_preview',
    defaultMessage: 'Close preview',
  },
  configure_columns: {
    id: 'search.columns.configure',
    defaultMessage: 'Configure columns',
  },
  configure_columns_placeholder: {
    id: 'search.columns.configure_placeholder',
    defaultMessage: 'Search for a column...',
  },
});

class FacetedEntitySearch extends React.Component {
  constructor(props) {
    super(props);

    this.getCurrentPreviewIndex = this.getCurrentPreviewIndex.bind(this);
    this.onColumnsEdit = this.onColumnsEdit.bind(this);
    this.onColumnsReset = this.onColumnsReset.bind(this);
    this.showNextPreview = this.showNextPreview.bind(this);
    this.showPreviousPreview = this.showPreviousPreview.bind(this);
    this.showPreview = this.showPreview.bind(this);
    this.closePreview = this.closePreview.bind(this);
  }

  getCurrentPreviewIndex() {
    const { location } = this.props;
    const parsedHash = queryString.parse(location.hash);
    return this.props.result.results.findIndex(
      (entity) => entity.id === parsedHash['preview:id']
    );
  }

  showNextPreview(event) {
    const currentSelectionIndex = this.getCurrentPreviewIndex();
    const nextEntity = this.props.result.results[1 + currentSelectionIndex];

    if (nextEntity && currentSelectionIndex >= 0) {
      event.preventDefault();
      this.showPreview(nextEntity);
    }
  }

  showPreviousPreview(event) {
    event.preventDefault();
    const currentSelectionIndex = this.getCurrentPreviewIndex();
    const previousEntity = this.props.result.results[currentSelectionIndex - 1];
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

  onColumnsEdit(edited) {
    const { columns, navigate, location } = this.props;
    const next = columns.find(({ name }) => name === edited.name)
      ? columns.filter(({ name }) => name !== edited.name)
      : [...columns, edited];
    setColumnsInHash(navigate, location, next);
  }

  onColumnsReset() {
    const { navigate, location } = this.props;
    setColumnsInHash(navigate, location, null);
  }

  render() {
    const {
      additionalFields = [],
      columns,
      children,
      query,
      result,
      intl,
      hasCustomColumns,
      navigate,
      location,
    } = this.props;

    const empty = (
      <ErrorSection
        icon="search"
        title={intl.formatMessage(messages.no_results_title)}
        description={intl.formatMessage(messages.no_results_description)}
      />
    );

    const exportLink = result.total > 0 ? result.links?.export : null;

    const hotkeysGroupLabel = {
      group: intl.formatMessage(messages.group_label),
    };

    return (
      <HotkeysContainer
        hotkeys={[
          {
            combo: 'j',
            label: intl.formatMessage(messages.next),
            onKeyDown: this.showNextPreview,
            ...hotkeysGroupLabel,
          },
          {
            combo: 'k',
            label: intl.formatMessage(messages.previous),
            onKeyDown: this.showPreviousPreview,
            ...hotkeysGroupLabel,
          },
          {
            combo: 'up',
            label: intl.formatMessage(messages.previous),
            onKeyDown: this.showPreviousPreview,
            ...hotkeysGroupLabel,
          },
          {
            combo: 'down',
            label: intl.formatMessage(messages.next),
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
          defaultFacets={defaultFacets}
          additionalFields={additionalFields}
          storageKey="searchConfig"
          className="FacetedEntitySearch"
          showQueryTags
        >
          {({ updateQuery }) => (
            <>
              {children}
              <div className="FacetedEntitySearch__controls">
                <SearchActionBar
                  result={result}
                  exportDisabled={!exportLink}
                  onExport={() => this.props.triggerQueryExport(exportLink)}
                >
                  <div className="SearchActionBar__secondary">
                    <SearchFieldSelect
                      onSelect={this.onColumnsEdit}
                      onReset={hasCustomColumns && this.onColumnsReset}
                      selected={columns}
                      inputProps={{
                        placeholder: intl.formatMessage(
                          messages.configure_columns_placeholder
                        ),
                      }}
                    >
                      <Button
                        icon="two-columns"
                        text={intl.formatMessage(messages.configure_columns)}
                      />
                    </SearchFieldSelect>
                  </div>
                </SearchActionBar>
              </div>
              <EntitySearch
                query={query}
                updateQuery={updateQuery}
                result={result}
                emptyComponent={empty}
                columns={[...additionalFields.map(getGroupField), ...columns]}
              />
            </>
          )}
        </FacetedLayout>
      </HotkeysContainer>
    );
  }
}
const mapStateToProps = (state, ownProps) => {
  const { query, location } = ownProps;
  const searchConfig = getSearchConfig();
  const facets = searchConfig?.facets || defaultFacets.map(getGroupField);
  const model = selectModel(state);

  // Read columns from URL hash
  const columnsFromHash = getColumnsFromHash(location);
  let columns = columnsFromHash || getDefaultColumns();

  // Resolve labels for property columns using the FTM model
  if (model?.getProperties) {
    const allProperties = model.getProperties();
    columns = columns.map((col) => {
      if (col.isProperty && !col.label) {
        const prop = allProperties.find((p) => p.name === col.name);
        if (prop) {
          return { ...col, label: prop.label, type: prop.type?.name };
        }
      }
      return col;
    });
  }

  // add any active facets to the list of displayed columns
  const activeFacetKeys = query.getList('facet');
  const activeFacets = activeFacetKeys
    .map((key) => {
      const sanitizedKey = key.replace('properties.', '');
      return facets.find((facet) => facet.name === sanitizedKey);
    })
    .filter((facet) => !!facet);

  return {
    hasCustomColumns: !!columnsFromHash,
    columns: _.uniqBy([...columns, ...activeFacets], (facet) => facet.name),
  };
};

export default compose(
  withRouter,
  connect(mapStateToProps, { triggerQueryExport }),
  injectIntl
)(FacetedEntitySearch);
