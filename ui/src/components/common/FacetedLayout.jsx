import React from 'react';
import queryString from 'query-string';
import { defineMessages, injectIntl } from 'react-intl';
import {
  Alignment,
  Button,
  Divider,
  Drawer,
  Intent,
  Position,
} from '@blueprintjs/core';
import { connect } from 'react-redux';
import c from 'classnames';

import { getSearchConfig, setSearchConfig } from 'app/storage';
import { getGroupField } from 'components/SearchField/util';
import DualPane from './DualPane';
import Facets from 'components/Facet/Facets';
import SearchFieldSelect from 'components/SearchField/SearchFieldSelect';
import QueryTags from 'components/QueryTags/QueryTags';

import './FacetedLayout.scss';

const SMALL_SCR_BREAKPOINT = 620;
const DEFAULT_STORAGE_KEY = 'searchConfig';

const messages = defineMessages({
  configure_facets: {
    id: 'faceted_layout.configure',
    defaultMessage: 'Configure filters',
  },
  configure_facets_placeholder: {
    id: 'faceted_layout.configure_placeholder',
    defaultMessage: 'Search for a filter...',
  },
  show_facets: {
    id: 'faceted_layout.show',
    defaultMessage: 'Show filters',
  },
  hide_facets: {
    id: 'faceted_layout.hide',
    defaultMessage: 'Hide filters',
  },
});

// Generic shell for a faceted-search screen. Owns the sidebar, the
// desktop/mobile breakpoint, the hide/show toggle and the navigation
// that facet toggles trigger. Callers render their own results body
// as `children` (either a React node or a render-prop function that
// receives `{ updateQuery }`).
//
// Storage of user facet picks is namespaced by `storageKey` so each
// consumer (global search, each entity tab) gets its own saved list.
class FacetedLayout extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      hideFacets: false,
      isMobile: false,
    };

    this.updateQuery = this.updateQuery.bind(this);
    this.toggleFacets = this.toggleFacets.bind(this);
    this.onFacetEdit = this.onFacetEdit.bind(this);
    this.onFacetReset = this.onFacetReset.bind(this);
    this.checkMobileWidth = this.checkMobileWidth.bind(this);
    this.ref = React.createRef();
  }

  componentDidMount() {
    window.addEventListener('resize', this.checkMobileWidth);
    this.checkMobileWidth();
  }

  componentWillUnmount() {
    window.removeEventListener('resize', this.checkMobileWidth);
  }

  checkMobileWidth() {
    const width = this.ref.current?.clientWidth;
    if (!width) {
      return;
    }

    if (width < SMALL_SCR_BREAKPOINT) {
      this.setState(({ isMobile }) => {
        if (!isMobile) {
          return { isMobile: true, hideFacets: true };
        }
      });
    } else {
      this.setState(({ isMobile }) => {
        if (isMobile) {
          return { isMobile: false, hideFacets: false };
        }
      });
    }
  }

  updateQuery(newQuery) {
    const { navigate, location } = this.props;
    // Close any open preview when the query changes — stale preview id
    // doesn't belong to the new result set.
    const parsedHash = queryString.parse(location.hash);
    parsedHash['preview:id'] = undefined;
    parsedHash['preview:type'] = undefined;

    navigate({
      pathname: location.pathname,
      search: newQuery.toLocation(),
      hash: queryString.stringify(parsedHash),
    });
  }

  toggleFacets() {
    this.setState(({ hideFacets }) => ({ hideFacets: !hideFacets }));
  }

  onFacetEdit(edited) {
    const { facets } = this.props;
    const next = facets.find(({ name }) => name === edited.name)
      ? facets.filter(({ name }) => name !== edited.name)
      : [...facets, edited];
    this.saveFacets(next);
  }

  onFacetReset() {
    this.saveFacets(null);
  }

  saveFacets(facets) {
    const { navigate, location, storageKey = DEFAULT_STORAGE_KEY } = this.props;
    setSearchConfig(storageKey, { facets });

    // Force re-render without polluting history — mapStateToProps needs
    // to re-read the storage to pick up the new facet list.
    navigate(
      {
        pathname: location.pathname,
        search: location.search,
        hash: location.hash,
      },
      { replace: true }
    );
  }

  renderFacets() {
    const {
      additionalFields = [],
      facets,
      query,
      result,
      intl,
      hasCustomFacets,
    } = this.props;

    return (
      <div className="FacetedLayout__facets">
        <Facets
          query={query}
          result={result}
          updateQuery={this.updateQuery}
          facets={[...additionalFields.map(getGroupField), ...facets]}
          isCollapsible
        />
        <SearchFieldSelect
          onSelect={this.onFacetEdit}
          onReset={hasCustomFacets && this.onFacetReset}
          selected={facets}
          filterProps={(prop) => prop?.type?.name !== 'text'}
          inputProps={{
            placeholder: intl.formatMessage(
              messages.configure_facets_placeholder
            ),
          }}
        >
          <Button
            icon="filter-list"
            text={intl.formatMessage(messages.configure_facets)}
          />
        </SearchFieldSelect>
      </div>
    );
  }

  renderContent() {
    const { children, query, showQueryTags = true } = this.props;
    return (
      <>
        {showQueryTags && (
          <QueryTags query={query} updateQuery={this.updateQuery} />
        )}
        {typeof children === 'function'
          ? children({ updateQuery: this.updateQuery })
          : children}
      </>
    );
  }

  render() {
    const { intl, className, hideSidebarWhenEmpty, query, result } = this.props;
    const { hideFacets, isMobile } = this.state;
    const toggleButtonLabel = intl.formatMessage(
      messages[hideFacets ? 'show_facets' : 'hide_facets']
    );

    // When there's nothing to facet and the user hasn't applied any
    // filters themselves, skip the sidebar entirely — the picker would
    // just show empty counts. Callers opt in via `hideSidebarWhenEmpty`.
    const suppressSidebar =
      hideSidebarWhenEmpty &&
      result.total === 0 &&
      query.filters().length === 0;

    if (suppressSidebar) {
      return <div className="FacetedLayout__root">{this.renderContent()}</div>;
    }

    return (
      <div ref={this.ref} className="FacetedLayout__root">
        <DualPane className={c('FacetedLayout', className, { collapsed: hideFacets })}>
          {!isMobile && (
            <DualPane.SidePane className="FacetedLayout__side-placeholder">
              <Drawer
                autoFocus={false}
                enforceFocus={false}
                hasBackdrop={false}
                usePortal={false}
                isOpen={!hideFacets}
                canEscapeKeyClose={false}
                canOutsideClickClose={false}
                position={Position.LEFT}
                size={325}
              >
                {this.renderFacets()}
              </Drawer>
            </DualPane.SidePane>
          )}
          {isMobile && (
            <div>
              <Button
                className="FacetedLayout__mobile-expand-toggle"
                onClick={this.toggleFacets}
                text={toggleButtonLabel}
                icon={hideFacets ? 'add' : 'remove'}
                alignText={Alignment.LEFT}
                intent={Intent.PRIMARY}
                fill={false}
                large
                outlined
              />
              <Divider />
              {!hideFacets && this.renderFacets()}
            </div>
          )}
          <DualPane.ContentPane>{this.renderContent()}</DualPane.ContentPane>
          {!isMobile && (
            <div className="FacetedLayout__expand-toggle">
              <Button
                onClick={this.toggleFacets}
                icon={hideFacets ? 'chevron-right' : 'chevron-left'}
                aria-label={toggleButtonLabel}
                outlined
                className="FacetedLayout__expand-toggle__button"
              />
            </div>
          )}
        </DualPane>
      </div>
    );
  }
}

const mapStateToProps = (_state, ownProps) => {
  const { storageKey = DEFAULT_STORAGE_KEY, defaultFacets = [] } = ownProps;
  const searchConfig = getSearchConfig(storageKey);
  // Filter out unknown group-field names — `getGroupField` returns
  // undefined for any key not registered in SearchField/util.js, and
  // one `undefined` in the list crashes `Facets` at `.name` access.
  const facets = (
    searchConfig?.facets || defaultFacets.map(getGroupField)
  ).filter(Boolean);
  return {
    facets,
    hasCustomFacets: !!searchConfig?.facets,
  };
};

export default connect(mapStateToProps)(injectIntl(FacetedLayout));
