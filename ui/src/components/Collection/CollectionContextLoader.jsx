import { PureComponent } from 'react';
import { compose } from 'redux';
import { connect } from 'react-redux';

import withRouter from 'app/withRouter';
import { collectionXrefFacetsQuery } from 'queries';
import { fetchCollection, queryCollectionXref, fetchCollectionDiscovery, forceMutate } from 'actions';
import { selectCollection, selectCollectionXrefResult, selectCollectionDiscovery } from 'selectors';
import timestamp from 'util/timestamp';

class CollectionContextLoader extends PureComponent {
  constructor(props) {
    super(props);
    this.state = { timeout: null };
    this.fetchRefresh = this.fetchRefresh.bind(this);
  }

  componentDidMount() {
    this.fetchRefresh();
    this.fetchIfNeeded();
  }

  componentDidUpdate() {
    this.fetchIfNeeded();
  }

  componentWillUnmount() {
    clearTimeout(this.state.timeout);
  }

  fetchIfNeeded() {
    const { collectionId, collection } = this.props;

    if (collection.shouldLoadDeep) {
      const refresh = collection.shallow === false;
      this.props.fetchCollection({ id: collectionId, refresh });
    }

    const { xrefResult, xrefQuery } = this.props;
    if (xrefResult.shouldLoad) {
      this.props.queryCollectionXref({ query: xrefQuery, result: xrefResult });
    }

    const { discoveryResult } = this.props;
    if (discoveryResult.shouldLoad) {
      this.props.fetchCollectionDiscovery({ id: collectionId });
    }
  }

  fetchRefresh() {
    const { collection } = this.props;
    const { status } = collection;
    clearTimeout(this.state.timeout);
    const staleDuration = status.active ? 10000 : 30000;
    const age = timestamp() - collection.loadedAt;
    const shouldRefresh = age > staleDuration && !collection.isPending;
    if (shouldRefresh) {
      // this.props.forceMutate();
      this.props.fetchCollection(collection);
    }
    const timeout = setTimeout(this.fetchRefresh, 10000);
    this.setState({ timeout });
  }

  render() {
    return this.props.children;
  }
}

const mapStateToProps = (state, ownProps) => {
  const { location, collectionId } = ownProps;
  const xrefQuery = collectionXrefFacetsQuery(location, collectionId);
  return {
    collection: selectCollection(state, collectionId),
    xrefQuery,
    xrefResult: selectCollectionXrefResult(state, xrefQuery),
    discoveryResult: selectCollectionDiscovery(state, collectionId),
  };
};

const mapDispatchToProps = {
  forceMutate,
  fetchCollection,
  queryCollectionXref,
  fetchCollectionDiscovery,
};

export default compose(
  withRouter,
  connect(mapStateToProps, mapDispatchToProps)
)(CollectionContextLoader);
