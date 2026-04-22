import { Component } from 'react';
import { connect } from 'react-redux';
import withRouter from 'app/withRouter';
import { injectIntl } from 'react-intl';
import c from 'classnames';
import { entityThreadQuery } from 'queries';
import { selectThreadResult } from 'selectors';
import EmailPropertyValues from 'components/common/EmailPropertyValues';
import { Entity, Property, Schema, Skeleton } from 'components/common';

import './EntityThreadMode.scss';

class EntityThreadMode extends Component {
  render() {
    const { result, entity } = this.props;

    const columns = entity.schema.getFeaturedProperties();
    const skeletonItems = [...Array(15).keys()];

    return (
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
    );
  }

  renderRow(columns, entity) {
    return (
      <tr
        key={entity.id}
        className={c('nowrap', {
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
}

const mapStateToProps = (state, ownProps) => {
  const { entity, location } = ownProps;
  const query = entityThreadQuery(location, entity.id);
  const result = selectThreadResult(state, query);
  return { query, result };
};

EntityThreadMode = connect(mapStateToProps)(EntityThreadMode);
EntityThreadMode = withRouter(EntityThreadMode);
EntityThreadMode = injectIntl(EntityThreadMode);
export default EntityThreadMode;
