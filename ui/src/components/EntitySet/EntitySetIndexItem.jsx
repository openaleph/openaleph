import React from 'react';
import { FormattedMessage } from 'react-intl';
import { Link } from 'react-router-dom';
import { Alignment, Button, Classes, Icon, H6 } from '@blueprintjs/core';
import {
  Collection,
  Date,
  EntitySet,
  Skeleton,
  Summary,
} from 'components/common';
import getEntitySetLink from 'util/getEntitySetLink';

import './EntitySetIndexItem.scss';

class EntitySetIndexItem extends React.PureComponent {
  renderButton() {
    const { entitySet, isPending, onSelect } = this.props;

    let text;
    if (isPending) {
      text = <Skeleton.Text type="span" length={50} />;
    } else {
      text = (
        <EntitySet.Label
          className="index-item__title__text"
          entitySet={entitySet}
          truncate="40"
        />
      );
    }

    return (
      <Button
        minimal
        className="EntitySetIndexItem index-item"
        alignText={Alignment.LEFT}
        onClick={() => onSelect(entitySet)}
        icon={<EntitySet.Icon entitySet={entitySet} />}
      >
        {text}
      </Button>
    );
  }

  renderListItem() {
    const { entitySet, isPending, showCollection } = this.props;

    if (isPending) {
      return (
        <div className="index-item__link">
          <div className="EntitySetIndexItem__flex-content">
            <H6 className="index-item__title">
              <Skeleton.Text type="span" length={30} />
            </H6>
            <p className="index-item__details">
              {showCollection && (
                <Skeleton.Text
                  className="index-item__details__item"
                  type="span"
                  length={20}
                />
              )}
              <Skeleton.Text
                className="index-item__details__item"
                type="span"
                length={20}
              />
            </p>
          </div>
        </div>
      );
    }

    return (
      <Link to={getEntitySetLink(entitySet)} className="index-item__link">
        <div className="EntitySetIndexItem__flex-content">
          <H6 className="index-item__title">
            <EntitySet.Label
              className="index-item__title__text"
              entitySet={entitySet}
              icon
            />
          </H6>
          <span className="index-item__details">
            {showCollection && (
              <span className="index-item__details__item">
                <Collection.Label
                  collection={entitySet.collection}
                  className={Classes.TEXT_MUTED}
                />
              </span>
            )}
            <span className="index-item__details__item">
              <Icon icon="time" iconSize={14} />
              <FormattedMessage
                id="entitySet.last_updated"
                defaultMessage="Updated {date}"
                values={{
                  date: <Date value={entitySet.updated_at} />,
                }}
              />
            </span>
          </span>
        </div>
        {entitySet.summary && (
          <Summary
            text={entitySet.summary}
            className="index-item__summary"
            truncate={2}
          />
        )}
      </Link>
    );
  }

  render() {
    const { onSelect } = this.props;
    const content = onSelect ? this.renderButton() : this.renderListItem();

    return <li className="EntitySetIndexItem index-item">{content}</li>;
  }
}

export default EntitySetIndexItem;
