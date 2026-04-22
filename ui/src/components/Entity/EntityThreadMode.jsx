import { Component } from 'react';
import { connect } from 'react-redux';
import withRouter from 'app/withRouter';
import { defineMessages, injectIntl } from 'react-intl';
import c from 'classnames';
import queryString from 'query-string';
import { entityThreadQuery } from 'queries';
import { selectThreadResult } from 'selectors';
import togglePreview from 'util/togglePreview';
import EmailPropertyValues from 'components/common/EmailPropertyValues';
import {
  Entity,
  Property,
  Schema,
  Skeleton,
  HotkeysContainer,
} from 'components/common';

import './EntityThreadMode.scss';

const messages = defineMessages({
  next_preview: {
    id: 'entity.thread.next_preview',
    defaultMessage: 'Preview next {schema}',
  },
  previous_preview: {
    id: 'entity.thread.previous_preview',
    defaultMessage: 'Preview previous {schema}',
  },
  close_preview: {
    id: 'entity.thread.close_preview',
    defaultMessage: 'Close preview',
  },
});

class EntityThreadMode extends Component {
  constructor(props) {
    super(props);
    this.getCurrentPreviewIndex = this.getCurrentPreviewIndex.bind(this);
    this.showNextPreview = this.showNextPreview.bind(this);
    this.showPreviousPreview = this.showPreviousPreview.bind(this);
    this.showPreview = this.showPreview.bind(this);
    this.closePreview = this.closePreview.bind(this);
  }

  render() {
    const { intl, result, entity } = this.props;

    const schema = entity.schema;
    const schemaLabel = schema.label;
    const columns = schema.getFeaturedProperties();
    const skeletonItems = [...Array(15).keys()];

    return (
      <HotkeysContainer
        hotkeys={[
          {
            combo: 'j',
            label: intl.formatMessage(messages.next_preview, { schema: schemaLabel }),
            onKeyDown: this.showNextPreview,
            group: schema.plural,
          },
          {
            combo: 'k',
            label: intl.formatMessage(messages.previous_preview, { schema: schemaLabel }),
            onKeyDown: this.showPreviousPreview,
            group: schema.plural,
          },
          {
            combo: 'up',
            label: intl.formatMessage(messages.next_preview, { schema: schemaLabel }),
            onKeyDown: this.showPreviousPreview,
            group: schema.plural,
          },
          {
            combo: 'down',
            label: intl.formatMessage(messages.previous_preview, { schema: schemaLabel }),
            onKeyDown: this.showNextPreview,
            group: schema.plural,
          },
          {
            combo: 'esc',
            label: intl.formatMessage(messages.close_preview),
            onKeyDown: this.closePreview,
            group: schema.plural,
          },
        ]}
      >
        <div className="EntityThreadMode">
          <table className="data-table references-data-table">
            <thead>
              <tr>
                {columns.map((prop) => (
                  <th key={prop.name}>{prop.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.results?.map((entity) => this.renderRow(columns, entity))}
              {result.isPending && (
                skeletonItems.map((index) => this.renderSkeleton(columns, index))
              )}
            </tbody>
          </table>
        </div>
      </HotkeysContainer>
    );
  }

  renderRow(columns, entity) {
    const { previewId } = this.props;

    return (
      <tr
        key={entity.id}
        className={c('nowrap', {
          active: previewId === entity.id,
          current: this.props.entity.id === entity.id,
        })}
      >
        {columns.map((prop) => this.renderCell(prop, entity))}
      </tr>
    );
  }

  renderCell(prop, entity) {
    const { isPreview } = this.props;

    const propVal = prop.qname === 'Email:from' || prop.qname === 'Email:to' ? (
      // This is a workaround to make the email sender/recipient a link
      <EmailPropertyValues
        entity={entity}
        prop={prop.name}
        preview={!isPreview}
      />
    ) : (
      <Property.Values
        prop={prop}
        values={entity.getProperty(prop.name)}
        translitLookup={entity.latinized}
        preview={!isPreview}
        showTime={true}
      />
    );

    if (entity.schema.caption.includes(prop.name)) {
      return (
        <td key={prop.name} className="entity">
          <Entity.Link entity={entity} preview={!isPreview}>
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

  renderSkeleton(columns, index) {
    return (
      <tr key={index} className="nowrap skeleton">
        {columns.map((prop) => (
          <td key={prop.name}>
            <Skeleton.Text type="span" length={10} />
          </td>
        ))}
      </tr>
    );
  }

  getCurrentPreviewIndex() {
    const { previewId, results } = this.props;
    return results.findIndex(
      (entity) => entity.id === previewId
    );
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
}

const mapStateToProps = (state, ownProps) => {
  const { entity, location } = ownProps;
  const query = entityThreadQuery(location, entity.id);
  const result = selectThreadResult(state, query);
  const results = result.results;

  const parsedHash = queryString.parse(location.hash);
  const previewId = parsedHash["preview:id"];
  return { query, result, results, previewId };
};

EntityThreadMode = connect(mapStateToProps)(EntityThreadMode);
EntityThreadMode = withRouter(EntityThreadMode);
EntityThreadMode = injectIntl(EntityThreadMode);
export default EntityThreadMode;
