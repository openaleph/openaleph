import { PureComponent } from 'react';
import { compose } from 'redux';
import { connect } from 'react-redux';

import withRouter from 'app/withRouter';
import {
  fetchEntity,
  fetchEntityTags,
  queryEntities,
  querySimilar,
  queryNearby,
  queryEntityExpand,
} from 'actions';
import {
  selectEntity,
  selectEntityTags,
  selectEntitiesResult,
  selectSimilarResult,
  selectNearbyResult,
  selectEntityExpandResult,
} from 'selectors';
import {
  entitySimilarQuery,
  entityNearbyQuery,
  folderDocumentsQuery,
  entityReferencesQuery,
} from 'queries';

class EntityContextLoader extends PureComponent {
  componentDidMount() {
    this.fetchIfNeeded();
  }

  componentDidUpdate() {
    this.fetchIfNeeded();
  }

  fetchIfNeeded() {
    const { entityId, entity, tagsResult, isPreview } = this.props;
    if (entity.shouldLoadDeep) {
      this.props.fetchEntity({ id: entityId });
    }

    if (tagsResult.shouldLoad) {
      this.props.fetchEntityTags({ id: entityId });
    }

    const { expandQuery, expandResult } = this.props;
    if (expandResult.shouldLoad) {
      this.props.queryEntityExpand({ query: expandQuery });
    }

    const { similarQuery, similarResult } = this.props;
    const showSimilar = entity?.schema?.matchable && !isPreview;
    if (showSimilar && similarResult.shouldLoad) {
      this.props.querySimilar({ query: similarQuery });
    }

    const { nearbyQuery, nearbyResult } = this.props;
    const showNearby = entity?.schema?.isA('Address') && !isPreview;
    if (showNearby && nearbyResult.shouldLoad) {
      this.props.queryNearby({ query: nearbyQuery });
    }

    const { childrenResult, childrenQuery } = this.props;
    if (entity?.schema?.isA('Folder') && childrenResult.shouldLoad) {
      this.props.queryEntities({ query: childrenQuery });
    }
  }

  render() {
    return this.props.children;
  }
}

const mapStateToProps = (state, ownProps) => {
  const { entityId, location } = ownProps;
  const similarQuery = entitySimilarQuery(location, entityId);
  const nearbyQuery = entityNearbyQuery(location, entityId);
  const childrenQuery = folderDocumentsQuery(location, entityId, undefined);
  const expandQuery = entityReferencesQuery(entityId);
  return {
    entity: selectEntity(state, entityId),
    tagsResult: selectEntityTags(state, entityId),
    similarQuery,
    similarResult: selectSimilarResult(state, similarQuery),
    nearbyQuery,
    nearbyResult: selectNearbyResult(state, nearbyQuery),
    expandQuery,
    expandResult: selectEntityExpandResult(state, expandQuery),
    childrenQuery,
    childrenResult: selectEntitiesResult(state, childrenQuery),
  };
};

const mapDispatchToProps = {
  queryEntities,
  querySimilar,
  queryNearby,
  queryEntityExpand,
  fetchEntity,
  fetchEntityTags,
};

export default compose(
  withRouter,
  connect(mapStateToProps, mapDispatchToProps)
)(EntityContextLoader);
