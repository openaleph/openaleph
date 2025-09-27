import React from 'react';
import { compose } from 'redux';
import { connect } from 'react-redux';
import { Drawer, Position, Tag } from '@blueprintjs/core';
import { Link } from 'react-router-dom';
import { isLangRtl } from 'react-ftm';

import withRouter from 'app/withRouter';
import EntityContextLoader from 'components/Entity/EntityContextLoader';
import EntityHeading from 'components/Entity/EntityHeading';
import EntityToolbar from 'components/Entity/EntityToolbar';
import EntityViews from 'components/Entity/EntityViews';
import EntityImage from 'components/Entity/EntityImage';
import ProfileCallout from 'components/Profile/ProfileCallout';
import { SectionLoading, ErrorSection } from 'components/common';
import {
  selectEntity,
  selectEntityView,
  selectLocale,
  selectServiceUrl,
} from 'selectors';
import queryString from 'query-string';
import togglePreview from 'util/togglePreview';
import { setRecentlyViewedItem } from 'app/storage';

import 'components/common/ItemOverview.scss';
import './EntityPreview.scss';

export class EntityPreview extends React.Component {
  constructor(props) {
    super(props);
    this.onClose = this.onClose.bind(this);
    this.onUnmount = this.onUnmount.bind(this);
  }

  componentDidMount() {
    window.addEventListener('beforeunload', this.onUnmount);
  }

  componentWillUnmount() {
    this.onUnmount();
    window.removeEventListener('beforeunload', this.onUnmount);
  }

  onUnmount() {
    setRecentlyViewedItem(this.props.entityId);
  }

  onClose(event) {
    const { navigate, location } = this.props;
    this.onUnmount();
    togglePreview(navigate, location, null);
  }

  renderTags() {
    const { entity } = this.props;
    const tags = entity.tags || [];

    if (!tags.length) {
      return null;
    }

    return (
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.15rem', marginBottom: '0.25rem' }}>
        {tags.map((tag) => (
          <Link
            key={tag}
            to={`/search?filter:tags=${encodeURIComponent(tag)}`}
            style={{ textDecoration: 'none' }}
          >
            <Tag
              minimal
              intent="primary"
              icon="tag"
              style={{ fontSize: '0.65rem', padding: '0.1rem 0.3rem', fontWeight: 300 }}
            >
              {tag}
            </Tag>
          </Link>
        ))}
      </div>
    );
  }

  renderContext() {
    const { entity, activeMode, profile, ftmAssetsApi } = this.props;
    if (entity.isError) {
      return <ErrorSection error={entity.error} />;
    }
    if (!entity.id || !entity?.schema?.name) {
      return <SectionLoading />;
    }
    return (
      <div className="ItemOverview preview">
        <div className="ItemOverview__heading">
          <EntityImage api={ftmAssetsApi} entity={entity} thumbnail />
          <span>
            {this.renderTags()}
            <EntityHeading entity={entity} isPreview />
          </span>
        </div>
        {entity.profileId && profile && (
          <div className="ItemOverview__callout">
            <ProfileCallout entity={entity} />
          </div>
        )}
        <div className="ItemOverview__content">
          <EntityViews entity={entity} activeMode={activeMode} isPreview />
        </div>
      </div>
    );
  }

  render() {
    const { entityId, entity, hidden, locale, profile } = this.props;
    if (!entityId) {
      return null;
    }
    return (
      <EntityContextLoader entityId={entityId} isPreview>
        <Drawer
          className="EntityPreview"
          isOpen={!hidden}
          title={<EntityToolbar entity={entity} profile={profile} />}
          onOpened={this.onOpen}
          onClose={this.onClose}
          hasBackdrop={false}
          autoFocus={false}
          enforceFocus={false}
          position={isLangRtl(locale) ? Position.LEFT : Position.RIGHT}
          // canOutsideClickClose={false}
          portalClassName="EntityPreview__overlay-container"
        >
          <div className="EntityPreview__content">{this.renderContext()}</div>
        </Drawer>
      </EntityContextLoader>
    );
  }
}

const mapStateToProps = (state, ownProps) => {
  const parsedHash = queryString.parse(ownProps.location.hash);
  const entityId = parsedHash['preview:id'];
  const profile = parsedHash['preview:profile'] !== 'false';
  const activeMode = parsedHash['preview:mode'];

  return {
    entityId,
    profile,
    parsedHash,
    entity: selectEntity(state, entityId),
    activeMode: selectEntityView(state, entityId, activeMode, true, ownProps.location),
    locale: selectLocale(state),
    ftmAssetsApi: selectServiceUrl(state, 'ftm_assets'),
  };
};

export default compose(withRouter, connect(mapStateToProps))(EntityPreview);
