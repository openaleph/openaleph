import React, { Component } from 'react';
import { connect } from 'react-redux';
import { Button, Pre } from '@blueprintjs/core';
import { PagingButtons } from 'components/Toolbar';
import { queryEntities } from 'actions';
import { selectEntitiesResult, selectEntity } from 'selectors';
import TextViewer from 'viewers/TextViewer';

class PdfViewerPage extends Component {
  constructor(props) {
    super(props);
    this.state = { showTranslation: false };
  }

  componentDidMount() {
    this.fetchPage();
  }

  componentDidUpdate(prevProps) {
    const { query } = this.props;
    if (!query.sameAs(prevProps.query)) {
      this.fetchPage();
    }
  }

  fetchPage() {
    const { numPages, query, result } = this.props;
    if (numPages !== undefined && result.shouldLoad) {
      this.props.queryEntities({ query });
    }
  }

  render() {
    const { document, dir, entity, numPages, page } = this.props;
    const { showTranslation } = this.state;
    const hasTranslation = !!entity?.getFirst?.('translatedText');
    const displayTranslation = showTranslation && hasTranslation;

    return (
      <>
        <PagingButtons
          document={document}
          numberOfPages={numPages}
          page={page}
          showRotateButtons={false}
          extraButtons={
            hasTranslation ? (
              <Button
                icon="translate"
                minimal
                small
                active={showTranslation}
                onClick={() =>
                  this.setState({ showTranslation: !showTranslation })
                }
              >
                {`Show ${showTranslation ? 'original' : 'translation'}`}
              </Button>
            ) : null
          }
        />
        {displayTranslation ? (
          <Pre className="TextViewer" dir={dir}>
            {entity?.getFirst?.('translatedText')}
          </Pre>
        ) : (
          <TextViewer document={entity} dir={dir} noStyle />
        )}
      </>
    );
  }
}

const mapStateToProps = (state, ownProps) => {
  const { query } = ownProps;

  const result = selectEntitiesResult(state, query);

  const entity = result.results.length
    ? result.results[0]
    : selectEntity(state, undefined);

  return {
    query,
    result,
    entity,
  };
};

export default connect(mapStateToProps, { queryEntities })(PdfViewerPage);
