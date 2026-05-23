import React from 'react';
import { connect } from 'react-redux';
import { FormattedMessage } from 'react-intl';
import { Classes, Callout, Intent } from '@blueprintjs/core';
import c from 'classnames';
import { Entity, Schema, RelativeTime } from 'components/common';
import { selectMetadata } from 'selectors';

import 'components/common/ItemOverview.scss';

class EntityHeading extends React.PureComponent {
  getEntityBanner(entity, bannerRules) {
    if (!bannerRules?.length) return null;
    
    for (const rule of bannerRules) {
      try {
        // eslint-disable-next-line no-new-func
        if (new Function('entity', `return ${rule.condition}`)(entity)) {
          return rule;
        }
      } catch {
        // Skip invalid conditions
      }
    }
    
    return null;
  }

  render() {
    const { entity, isProfile = false, metadata } = this.props;
    const lastViewedDate = entity.lastViewed
      ? new Date(parseInt(entity.lastViewed, 10))
      : Date.now();
    
    const bannerRules = metadata?.app?.entity_banner_rules || [];
    const banner = this.getEntityBanner(entity, bannerRules);

    return (
      <>
        <span
          className={c(Classes.TEXT_MUTED, 'ItemOverview__heading__subtitle')}
        >
          <Schema.Label schema={entity.schema} icon />
          {isProfile && (
            <>
              {' · '}
              <FormattedMessage
                id="profile.info.header"
                defaultMessage="Profile"
              />
            </>
          )}
        </span>
        <h1 className="ItemOverview__heading__title">
          {entity.schema.isThing() && <Entity.Label entity={entity} addClass />}
        </h1>
        {entity.lastViewed && (
          <span
            className={c(
              'ItemOverview__heading__last-viewed',
              Classes.TEXT_MUTED
            )}
          >
            <FormattedMessage
              id="entity.info.last_view"
              defaultMessage="Last viewed {time}"
              values={{ time: <RelativeTime date={lastViewedDate} /> }}
            />
          </span>
        )}
        
        {banner && (
          <div className="ItemOverview__heading__banner" style={{ marginTop: '12px' }}>
            <Callout intent={Intent[banner.intent.toUpperCase()]} icon={banner.icon}>
              {banner.message}
            </Callout>
          </div>
        )}
      </>
    );
  }
}

const mapStateToProps = (state) => ({
  metadata: selectMetadata(state),
});

export default connect(mapStateToProps)(EntityHeading);
