import _ from 'lodash';
import { Component } from 'react';
import { defineMessages, FormattedMessage, injectIntl } from 'react-intl';
import { compose } from 'redux';
import { connect } from 'react-redux';
import { Callout, Tag, Intent } from '@blueprintjs/core';
import queryString from 'query-string';
import c from 'classnames';

import withRouter from 'app/withRouter';
import { queryPercolate } from 'actions';
import { selectPercolateResult } from 'selectors';
import {
  ErrorSection,
  HotkeysContainer,
  QueryInfiniteLoad,
  Entity,
  Collection,
  Schema,
  Skeleton,
  SearchHighlight,
  Topic,
} from 'components/common';
import { entityPercolateQuery } from 'queries';
import ensureArray from 'util/ensureArray';
import togglePreview from 'util/togglePreview';

import './EntityScreeningMode.scss';

// Danger: sanctions, enforcement, crime — highest risk signals
const DANGER_TOPICS = new Set([
  'sanction', 'sanction.linked', 'sanction.counter',
  'debarment', 'wanted', 'asset.frozen',
  'export.control', 'export.control.linked',
  'crime', 'crime.fraud', 'crime.cyber', 'crime.fin', 'crime.env',
  'crime.theft', 'crime.war', 'crime.boss', 'crime.terror',
  'crime.traffick', 'crime.traffick.drug', 'crime.traffick.human',
  'forced.labor',
]);

// Warning: PEP, political exposure, risk indicators
const WARNING_TOPICS = new Set([
  'role.pep', 'role.pep.frmr', 'role.pep.intl', 'role.pep.natl',
  'role.rca', 'role.pol', 'role.judge', 'role.civil', 'role.diplo',
  'role.oligarch', 'role.spy',
  'export.risk', 'invest.risk',
  'reg.action', 'reg.warn',
  'mare.detained', 'mare.shadow', 'mare.sts',
  'corp.offshore', 'corp.shell', 'corp.disqual',
]);

function getTopicIntent(topic) {
  if (DANGER_TOPICS.has(topic)) return Intent.DANGER;
  if (WARNING_TOPICS.has(topic)) return Intent.WARNING;
  return Intent.NONE;
}

const messages = defineMessages({
  empty: {
    id: 'entity.screening.empty',
    defaultMessage: 'No entity mentions found in this document.',
  },
  group_label: {
    id: 'entity.screening.group_label',
    defaultMessage: 'Screening results preview',
  },
  next_preview: {
    id: 'entity.screening.next_preview',
    defaultMessage: 'Preview next match',
  },
  previous_preview: {
    id: 'entity.screening.previous_preview',
    defaultMessage: 'Preview previous match',
  },
  close_preview: {
    id: 'entity.screening.close_preview',
    defaultMessage: 'Close preview',
  },
});

class EntityScreeningMode extends Component {
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
          id="entity.screening.found_text"
          defaultMessage={`Found {resultCount}
            {resultCount, plural, one {entity mention} other {entity mentions}}
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
                id="entity.screening.entity"
                defaultMessage="Mentioned entity"
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

  renderTopicTags(entity) {
    const topics = entity.getProperty ? entity.getProperty('topics') : ensureArray(entity?.properties?.topics);
    if (!topics.length) return null;

    return (
      <span className="EntityScreeningMode__topics">
        {topics.map((topic) => (
          <Tag
            key={topic}
            minimal
            round
            intent={getTopicIntent(topic)}
          >
            <Topic.Name code={topic} />
          </Tag>
        ))}
      </span>
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
            {this.renderTopicTags(entity)}
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
    const { intl, query, result, results } = this.props;
    const skeletonItems = [...Array(10).keys()];

    if (result.total === 0) {
      return (
        <ErrorSection
          icon="shield"
          title={intl.formatMessage(messages.empty)}
        />
      );
    }

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
        <div className="EntityScreeningMode">
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
            fetch={this.props.queryPercolate}
          />
        </div>
      </HotkeysContainer>
    );
  }
}

const mapStateToProps = (state, ownProps) => {
  const { entity, location } = ownProps;
  const query = entityPercolateQuery(location, entity.id);
  const result = selectPercolateResult(state, query);
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
  connect(mapStateToProps, { queryPercolate }),
  injectIntl
)(EntityScreeningMode);
