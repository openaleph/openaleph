import React from 'react';
import { Callout } from '@blueprintjs/core';
import { FormattedMessage } from 'react-intl';
import c from 'classnames';

import {
  Collection,
  Entity,
  SearchHighlight,
  Skeleton,
} from 'components/common';

// Shared 2-column "entity + collection" list for the single-entity
// tab modes whose output is a flat ranked list of entities with
// optional highlight snippets (Mentions, MoreLikeThis, Screening).
//
// Each caller just supplies:
//   - `result` / `results` / `previewId` (from Redux)
//   - `skeletonCount` (rows of loading placeholder)
//   - `entityHeader` – FormattedMessage descriptor for the left column
//   - `summary` – FormattedMessage descriptor for the "Found N ..." callout
//     (renders only when `result.total > 0`)
//   - `renderAccent(entity)` – optional element rendered *before* the
//     entity link (used by `EntityScreeningMode` for topic chips)

function EntityResultSummary({ result, summary }) {
  if (!summary || result.total === undefined || result.total === 0) {
    return null;
  }
  return (
    <Callout icon={null} intent="primary">
      <FormattedMessage
        {...summary}
        values={{
          resultCount: result.total,
          datasetCount: result.facets?.collection_id?.total ?? 0,
        }}
      />
    </Callout>
  );
}

function EntityListHeader({ entityHeader }) {
  return (
    <thead>
      <tr>
        <th>
          <span className="value">
            <FormattedMessage {...entityHeader} />
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

function EntityListSkeleton({ idx }) {
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

function EntityListRow({ entity, previewId, renderAccent }) {
  return (
    <>
      <tr
        key={entity.id}
        className={c({ active: previewId === entity.id })}
      >
        <td className="entity bordered">
          {renderAccent && renderAccent(entity)}
          <Entity.Link entity={entity} icon preview />
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

function EntityListTable(props) {
  const {
    result,
    results,
    previewId,
    skeletonCount = 10,
    entityHeader,
    summary,
    renderAccent,
    className,
  } = props;

  const skeletonItems = [...Array(skeletonCount).keys()];

  return (
    <div className={className}>
      <EntityResultSummary result={result} summary={summary} />
      <table className="data-table">
        <EntityListHeader entityHeader={entityHeader} />
        <tbody>
          {results.map((entity) => (
            <EntityListRow
              key={entity.id}
              entity={entity}
              previewId={previewId}
              renderAccent={renderAccent}
            />
          ))}
          {result.isPending &&
            skeletonItems.map((idx) => (
              <EntityListSkeleton key={idx} idx={idx} />
            ))}
        </tbody>
      </table>
    </div>
  );
}

export default EntityListTable;
