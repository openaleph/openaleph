import React from 'react';

import {
  FacetedLayout,
  PreviewHotkeys,
  QueryInfiniteLoad,
} from 'components/common';

// One-stop composition for a faceted result list. Wraps caller-supplied
// children in the three primitives every tab mode hand-wired before:
//
//   <PreviewHotkeys>      // j/k/up/down/esc + togglePreview
//     <FacetedLayout>     // sidebar, storage, mobile breakpoint, QueryTags
//       {children}        // caller's table / summary / etc.
//       <QueryInfiniteLoad />  // pagination auto-load
//     </FacetedLayout>
//   </PreviewHotkeys>
//
// Callers pass the mode-specific Redux action via `fetch`, a list of
// default facet names, and a `storageKey` for localStorage-namespaced
// facet picks. The render-prop `children` receives `{ updateQuery }`
// so internal controls (search submit, sort column click, etc.) can
// issue their own URL updates through the same path that FacetedLayout
// uses for facet clicks.

function FacetedResultList(props) {
  const {
    // Required
    query,
    result,
    fetch,
    navigate,
    location,
    previewGroupLabel,

    // Facet config
    defaultFacets = [],
    additionalFields = [],
    storageKey,
    hideSidebarWhenEmpty = false,
    // Tab modes start with the facet sidebar collapsed so the result
    // table has the full horizontal space by default. Users can open
    // the sidebar via the chevron toggle if they want to narrow. Main
    // search screens using `FacetedLayout` directly keep the default
    // (expanded).
    initialHideFacets = true,
    showQueryTags = true,
    className,

    // Opt out of preview hotkeys (EntitySimilarMode uses its own
    // judgment hotkeys instead).
    previewHotkeys = true,

    // Skip the facet sidebar entirely. Set this when the surface is
    // itself inside a preview panel (e.g. EntityReferencesMode under
    // isPreview) — there's no room for a sidebar and the table still
    // renders fine without one.
    showFacets = true,

    // Content
    children,
  } = props;

  const content = showFacets ? (
    <FacetedLayout
      query={query}
      result={result}
      navigate={navigate}
      location={location}
      defaultFacets={defaultFacets}
      additionalFields={additionalFields}
      storageKey={storageKey}
      hideSidebarWhenEmpty={hideSidebarWhenEmpty}
      initialHideFacets={initialHideFacets}
      showQueryTags={showQueryTags}
      className={className}
    >
      {(layoutProps) => (
        <>
          {typeof children === 'function' ? children(layoutProps) : children}
          <QueryInfiniteLoad query={query} result={result} fetch={fetch} />
        </>
      )}
    </FacetedLayout>
  ) : (
    <>
      {typeof children === 'function' ? children({}) : children}
      <QueryInfiniteLoad query={query} result={result} fetch={fetch} />
    </>
  );

  if (!previewHotkeys) {
    return content;
  }
  return (
    <PreviewHotkeys result={result} groupLabel={previewGroupLabel}>
      {content}
    </PreviewHotkeys>
  );
}

export default FacetedResultList;
