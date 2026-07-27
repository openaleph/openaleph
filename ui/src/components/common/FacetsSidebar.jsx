import React from 'react';
import { defineMessages, injectIntl } from 'react-intl';
import { Button } from '@blueprintjs/core';

import { getGroupField } from 'components/SearchField/util';
import Facets from 'components/Facet/Facets';
import SearchFieldSelect from 'components/SearchField/SearchFieldSelect';

const messages = defineMessages({
  configure_facets: {
    id: 'faceted_layout.configure',
    defaultMessage: 'Configure filters',
  },
  configure_facets_placeholder: {
    id: 'faceted_layout.configure_placeholder',
    defaultMessage: 'Search for a filter...',
  },
});

// Presentational facet-sidebar content: a collapsible list of facets
// with counts plus a "Configure filters" picker beneath. Purely a
// composition of `<Facets>` + `<SearchFieldSelect>`; no navigation or
// storage concerns of its own. Consumers (`FacetedLayout`,
// `MultiMentionsScreen`, …) wire `updateQuery`, `onFacetEdit`, and
// `onFacetReset` themselves so they can own the persistence and
// routing semantics appropriate to their surface.
function FacetsSidebar(props) {
  const {
    additionalFields = [],
    facets,
    query,
    result,
    updateQuery,
    onFacetEdit,
    onFacetReset,
    hasCustomFacets,
    intl,
  } = props;

  // Dedupe by name – `additionalFields` may overlap with user-picked
  // facets (e.g. both lists include `collection_id`). Two items with
  // the same name would render as two <li> siblings with the same
  // React key inside `<Facets>`.
  const merged = [];
  const seen = new Set();
  for (const facet of [...additionalFields.map(getGroupField), ...facets]) {
    if (!facet || seen.has(facet.name)) {
      continue;
    }
    seen.add(facet.name);
    merged.push(facet);
  }

  return (
    <div className="FacetsSidebar">
      <Facets
        query={query}
        result={result}
        updateQuery={updateQuery}
        facets={merged}
        isCollapsible
      />
      <SearchFieldSelect
        onSelect={onFacetEdit}
        onReset={hasCustomFacets ? onFacetReset : undefined}
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

export default injectIntl(FacetsSidebar);
