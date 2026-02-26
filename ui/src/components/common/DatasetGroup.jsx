import React, { Component } from 'react';
import { Classes } from '@blueprintjs/core';
import { Link } from 'react-router-dom';
import { connect } from 'react-redux';
import c from 'classnames';

import { fetchCollection } from 'actions';
import { selectCollection } from 'selectors';
import { Category, Count, Skeleton } from 'components/common';
import getCollectionLink from 'util/getCollectionLink';

class DatasetGroup extends Component {
  componentDidMount() {
    this.fetchCollections();
  }

  componentDidUpdate() {
    this.fetchCollections();
  }

  fetchCollections() {
    const { collections } = this.props;
    collections.forEach(({ id, collection }) => {
      if (collection.shouldLoad) {
        this.props.fetchCollection({ id });
      }
    });
  }

  render() {
    const { label, description, icon, collections, body } = this.props;
    const isPending = collections.some(({ collection }) => collection.isPending);
    const hasLoaded = collections.some(({ collection }) => !!collection.id);

    let bodyHtml = null;
    if (body) {
      try {
        bodyHtml = decodeURIComponent(escape(atob(body)));
      } catch (e) {
        bodyHtml = null;
      }
    }

    return (
      <div className="oa-dataset-group">
        <div className="oa-dataset-group__header">
          {icon && (
            <div className="oa-dataset-group__icon">
              <img src={`/static/${icon}`} alt="" />
            </div>
          )}
          <div className="oa-dataset-group__meta">
            <h3 className="oa-dataset-group__label">{label}</h3>
            {description && (
              <p className="oa-dataset-group__description">{description}</p>
            )}
          </div>
        </div>
        {bodyHtml && (
          <div
            className="oa-dataset-group__body"
            dangerouslySetInnerHTML={{ __html: bodyHtml }}
          />
        )}
        <div className="oa-dataset-group__list">
          {isPending && !hasLoaded && (
            <>
              <div className={c('oa-dataset-group__item', Classes.SKELETON)} style={{ height: 32 }} />
              <div className={c('oa-dataset-group__item', Classes.SKELETON)} style={{ height: 32 }} />
            </>
          )}
          {collections.map(({ id, collection }) => {
            if (!collection.id) return null;
            const link = getCollectionLink({ collection });
            return (
              <Link key={id} to={link} className="oa-dataset-group__item">
                <span className="oa-dataset-group__item__label">
                  {collection.label}
                </span>
                <span className="oa-dataset-group__item__info">
                  {collection.category && (
                    <span className="oa-dataset-group__item__category">
                      <Category.Label category={collection.category} />
                    </span>
                  )}
                  {collection.count !== undefined && (
                    <span className="oa-dataset-group__item__count">
                      <Count count={collection.count} />
                    </span>
                  )}
                </span>
              </Link>
            );
          })}
        </div>
      </div>
    );
  }
}

const mapStateToProps = (state, ownProps) => {
  const rawIds = (ownProps.collections || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);

  const collections = rawIds.map((id) => ({
    id,
    collection: selectCollection(state, id),
  }));

  return {
    label: ownProps.label,
    description: ownProps.description,
    icon: ownProps.icon,
    collections,
  };
};

export default connect(mapStateToProps, { fetchCollection })(DatasetGroup);
