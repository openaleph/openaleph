import React, { PureComponent } from 'react';
import { FormattedMessage } from 'react-intl';
import { Link } from 'react-router-dom';
import { Classes, Icon, H4 } from '@blueprintjs/core';
import {
  Date,
  Role,
  Category,
  Count,
  Country,
  Collection,
  Summary,
  Skeleton,
  Frequency,
} from 'components/common';
import getCollectionLink from 'util/getCollectionLink';

class CollectionIndexItem extends PureComponent {
  renderSkeleton = () => (
    <li className="index-item">
      <div className="index-item__count">
        <Count className={Classes.INTENT_PRIMARY} full isPending />
      </div>
      <H4 className="index-item__title">
        <Skeleton.Text type="span" length={20} />
      </H4>
      <Skeleton.Text className="index-item__summary" type="p" length={200} />
      <p className="index-item__details">
        <Skeleton.Text
          className="index-item__details__item"
          type="span"
          length={20}
        />
        <Skeleton.Text
          className="index-item__details__item"
          type="span"
          length={20}
        />
        <Skeleton.Text
          className="index-item__details__item"
          type="span"
          length={20}
        />
      </p>
    </li>
  );

  render() {
    const { collection, isPending } = this.props;

    if (isPending || !collection.id) {
      return this.renderSkeleton();
    }

    const link = getCollectionLink({ collection });

    return (
      <li className="index-item" key={collection.id}>
        <Link to={link} className="index-item__link">
          <div className="index-item__count">
            <Count
              className={Classes.INTENT_PRIMARY}
              count={collection.count}
              full
            />
          </div>
          <H4 className="index-item__title">
            <Collection.Label
              className="index-item__title__text"
              collection={collection}
              icon
            />
          </H4>
          {collection.summary && (
            <Summary
              text={collection.summary}
              className="index-item__summary"
              truncate={2}
            />
          )}
          <p className="index-item__details">
            <span className="index-item__details__item">
              <Category.Label category={collection.category} />
            </span>
            <span className="index-item__details__item">
              <Icon icon="time" />
              <FormattedMessage
                id="collection.last_updated"
                defaultMessage="Last updated {date}"
                values={{
                  date: <Date value={collection.updated_at} />,
                }}
              />
              {collection.frequency !== 'never' &&
                collection.frequency !== 'unknown' && (
                  <Frequency.Label frequency={collection.frequency} />
                )}
            </span>
            {collection.countries && collection.countries.length > 0 && (
              <span className="index-item__details__item">
                <Country.List codes={collection.countries} truncate={3} />
              </span>
            )}
            {collection.casefile && (
              <span className="index-item__details__item">
                <Role.List
                  roles={collection.team}
                  icon={false}
                  truncate={3}
                  truncateItem={20}
                  separateItems
                />
              </span>
            )}
          </p>
        </Link>
      </li>
    );
  }
}

export default CollectionIndexItem;
