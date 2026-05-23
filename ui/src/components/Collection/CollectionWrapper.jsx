import React, { Component } from 'react';
import { defineMessages, injectIntl } from 'react-intl';
import { compose } from 'redux';
import { connect } from 'react-redux';

import withRouter from 'app/withRouter';
import CollectionManageMenu from 'components/Collection/CollectionManageMenu';
import CollectionContextLoader from 'components/Collection/CollectionContextLoader';
import DocumentDropzone from 'components/Document/DocumentDropzone';
import collectionViewIds from 'components/Collection/collectionViewIds';
import { Breadcrumbs, SearchBox } from 'components/common';
import { collectionSearchQuery } from 'queries';
import { selectCollection } from 'selectors';
import getCollectionLink from 'util/getCollectionLink';

const messages = defineMessages({
  dataset: {
    id: 'dataset.search.placeholder',
    defaultMessage: 'Search this dataset',
  },
  casefile: {
    id: 'investigation.search.placeholder',
    defaultMessage: 'Search this investigation',
  },
});

export class CollectionWrapper extends Component {
  constructor(props) {
    super(props);
    this.onUploadSuccess = this.onUploadSuccess.bind(this);
    this.onSearch = this.onSearch.bind(this);
    this.onSynonymsChange = this.onSynonymsChange.bind(this);
  }

  onSearch(queryText) {
    const { collection, navigate, query } = this.props;
    const newQuery = query.set('q', queryText);
    navigate(
      getCollectionLink({
        collection,
        mode: collectionViewIds.SEARCH,
        search: newQuery.toLocation(),
      })
    );
  }

  onSynonymsChange(synonymsValue) {
    const { collection, navigate, query } = this.props;
    const newQuery = synonymsValue
      ? query.set('synonyms', 'true')
      : query.clear('synonyms');

    navigate(
      getCollectionLink({
        collection,
        mode: collectionViewIds.SEARCH,
        search: newQuery.toLocation(),
      }),
      { replace: true }
    );
  }

  onUploadSuccess() {
    const { collection, dropzoneFolderParent, navigate, location } = this.props;
    if (dropzoneFolderParent) {
      return;
    }

    navigate(
      getCollectionLink({
        collection,
        mode: collectionViewIds.DOCUMENTS,
        search: location.search,
      })
    );
  }

  render() {
    const {
      children,
      collection,
      collectionId,
      dropzoneFolderParent,
      query,
      intl,
      isCasefile,
    } = this.props;
    const message = intl.formatMessage(
      messages[isCasefile ? 'casefile' : 'dataset']
    );

    const search = (
      <SearchBox
        onSearch={this.onSearch}
        onSynonymsChange={this.onSynonymsChange}
        placeholder={message}
        query={query}
        inputProps={{ disabled: !collection?.id }}
        showSynonymsToggle={true}
        searchButton
      />
    );

    const operation = <CollectionManageMenu collection={collection} />;
    const breadcrumbs = (
      <Breadcrumbs
        operation={operation}
        search={search}
        type={isCasefile ? 'casefile' : 'dataset'}
      >
        <Breadcrumbs.Collection key="collection" collection={collection} />
      </Breadcrumbs>
    );

    return (
      <CollectionContextLoader collectionId={collectionId}>
        {breadcrumbs}
        <DocumentDropzone
          canDrop={collection.writeable}
          collection={collection}
          onUploadSuccess={this.onUploadSuccess}
          parent={dropzoneFolderParent}
        >
          {children}
        </DocumentDropzone>
      </CollectionContextLoader>
    );
  }
}

const mapStateToProps = (state, ownProps) => {
  const { collection, collectionId: id, location, forceCasefile } = ownProps;
  const collectionId = id || collection?.id;
  const isCasefile = forceCasefile || collection?.casefile;
  const collectionStatus = selectCollection(state, collectionId)?.status;
  const query = collectionSearchQuery(location, collectionId);

  return {
    collectionId,
    collection: { ...collection, status: collectionStatus },
    isCasefile,
    query,
  };
};

export default compose(
  withRouter,
  connect(mapStateToProps),
  injectIntl
)(CollectionWrapper);
