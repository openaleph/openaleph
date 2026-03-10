import React, { Component } from 'react';
import { Link } from 'react-router-dom';
import { connect } from 'react-redux';
import c from 'classnames';

import { fetchCollection } from 'actions';
import { selectCollection } from 'selectors';
import { Category, Count } from 'components/common';
import getCollectionLink from 'util/getCollectionLink';

class CollectionListItemBase extends Component {
  componentDidMount() {
    const { collection } = this.props;
    if (collection.shouldLoad) {
      this.props.fetchCollection({ id: this.props.id });
    }
  }

  componentDidUpdate() {
    const { collection } = this.props;
    if (collection.shouldLoad) {
      this.props.fetchCollection({ id: this.props.id });
    }
  }

  render() {
    const { collection } = this.props;
    if (!collection.id) return null;
    const link = getCollectionLink({ collection });
    return (
      <Link to={link} className="oa-collection-list__item">
        {collection.category && (
          <span className="oa-collection-list__item__category">
            <Category.Label category={collection.category} />
          </span>
        )}
        <span className="oa-collection-list__item__label">
          {collection.label}
        </span>
        <span className="oa-collection-list__item__info">
          {collection.count !== undefined && (
            <span className="oa-collection-list__item__count">
              <Count count={collection.count} />
            </span>
          )}
        </span>
      </Link>
    );
  }
}

const CollectionListItem = connect(
  (state, ownProps) => ({
    collection: selectCollection(state, ownProps.id),
  }),
  { fetchCollection }
)(CollectionListItemBase);

export default function CollectionList({ ids, dark }) {
  if (!ids || !ids.length) return null;
  return (
    <div className={c('oa-collection-list', { 'oa-collection-list--dark': dark })}>
      {ids.map((id) => (
        <CollectionListItem key={id} id={id} />
      ))}
    </div>
  );
}
