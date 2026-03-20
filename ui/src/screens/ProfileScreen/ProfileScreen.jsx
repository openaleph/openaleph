import React, { Component } from 'react';
import { compose } from 'redux';
import { connect } from 'react-redux';
import { Navigate } from 'react-router-dom';
import queryString from 'query-string';
import { injectIntl } from 'react-intl';

import withRouter from 'app/withRouter';
import Screen from 'components/Screen/Screen';
import EntityHeading from 'components/Entity/EntityHeading';
import EntityProperties from 'components/Entity/EntityProperties';
import ProfileViews from 'components/Profile/ProfileViews';
import LoadingScreen from 'components/Screen/LoadingScreen';
import ErrorScreen from 'components/Screen/ErrorScreen';
import ProfileCallout from 'components/Profile/ProfileCallout';
import { Breadcrumbs, DualPane, Schema } from 'components/common';
import getEntityLink from 'util/getEntityLink';
import {
  fetchCanonical,
  fetchCanonicalTags,
  querySimilar,
  queryCanonicalExpand,
} from 'actions';
import {
  selectCanonical,
  selectCanonicalView,
  selectCanonicalTags,
  selectSimilarResult,
  selectCanonicalExpandResult,
} from 'selectors';
import {
  canonicalSimilarQuery,
  canonicalReferencesQuery,
} from 'queries';

class ProfileScreen extends Component {
  componentDidMount() {
    this.fetchIfNeeded();
  }

  componentDidUpdate() {
    this.fetchIfNeeded();
  }

  fetchIfNeeded() {
    const { canonicalId, canonical, tagsResult } = this.props;
    if (!canonicalId) {
      return;
    }

    if (canonical.shouldLoadDeep) {
      this.props.fetchCanonical({ id: canonicalId });
    }

    if (tagsResult.shouldLoad) {
      this.props.fetchCanonicalTags({ id: canonicalId });
    }

    const { expandQuery, expandResult } = this.props;
    if (expandResult.shouldLoad) {
      this.props.queryCanonicalExpand({ query: expandQuery });
    }

    const { similarQuery, similarResult } = this.props;
    if (similarResult.shouldLoad) {
      this.props.querySimilar({ query: similarQuery });
    }

  }

  render() {
    const { canonical, canonicalId, viaEntityId, activeMode } = this.props;

    if (canonical.isError) {
      if (viaEntityId) {
        return <Navigate to={getEntityLink(viaEntityId, false)} replace />;
      }
      return <ErrorScreen error={canonical.error} />;
    }
    if (!canonical?.id || !canonical?.entity) {
      return <LoadingScreen />;
    }

    // Backend resolves stale canonical IDs to the current one
    if (canonical.id !== canonicalId) {
      return <Navigate to={`/profiles/${canonical.id}`} replace />;
    }

    const baseEntity = canonical.entity;
    const breadcrumbs = (
      <Breadcrumbs>
        <Breadcrumbs.Text>
          <Schema.Link schema={baseEntity.schema} plural />
        </Breadcrumbs.Text>
        <Breadcrumbs.Text text={canonical.label} icon="layers" />
      </Breadcrumbs>
    );

    return (
      <Screen title={canonical.label}>
        {breadcrumbs}
        <DualPane>
          <DualPane.SidePane className="ItemOverview profile">
            <div className="ItemOverview__heading">
              <EntityHeading entity={baseEntity} isProfile={true} />
            </div>
            <div className="ItemOverview__callout">
              <ProfileCallout canonical={canonical} viaEntityId={viaEntityId} />
            </div>
            <div className="ItemOverview__content">
              <EntityProperties entity={baseEntity} showMetadata={false} />
            </div>
          </DualPane.SidePane>
          <DualPane.ContentPane>
            <ProfileViews
              canonical={canonical}
              activeMode={activeMode}
              viaEntityId={viaEntityId}
            />
          </DualPane.ContentPane>
        </DualPane>
      </Screen>
    );
  }
}

const mapStateToProps = (state, ownProps) => {
  const { profileId } = ownProps.params;
  const canonicalId = profileId;
  const { location } = ownProps;
  const parsedHash = queryString.parse(location.hash);
  const similarQuery = canonicalSimilarQuery(location, canonicalId);
  const expandQuery = canonicalReferencesQuery(canonicalId);
  return {
    canonical: selectCanonical(state, canonicalId),
    canonicalId,
    viaEntityId: parsedHash.via,
    activeMode: selectCanonicalView(state, canonicalId, parsedHash.mode),
    tagsResult: selectCanonicalTags(state, canonicalId),
    similarQuery,
    similarResult: selectSimilarResult(state, similarQuery),
    expandQuery,
    expandResult: selectCanonicalExpandResult(state, expandQuery),
  };
};

const mapDispatchToProps = {
  querySimilar,
  queryCanonicalExpand,
  fetchCanonical,
  fetchCanonicalTags,
};

export default compose(
  withRouter,
  injectIntl,
  connect(mapStateToProps, mapDispatchToProps)
)(ProfileScreen);
