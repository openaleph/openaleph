import React from 'react';
import { compose } from 'redux';
import { connect } from 'react-redux';
import { H3, H4, Classes, Spinner, Icon } from '@blueprintjs/core';
import c from 'classnames';
import { useNavigate, useLocation } from 'react-router-dom';

import { selectCollectionDiscovery, selectModel } from 'selectors';
import { ErrorSection } from 'components/common';
import { Schema } from 'react-ftm';

import './CollectionDiscoveryMode.scss';

// TypeScript interfaces based on discover.yml schema
interface Term {
  name: string;
  count: number;
  label: string;
}

interface MentionedTerms {
  peopleMentioned: Term[];
  companiesMentioned: Term[];
  locationMentioned: Term[];
  namesMentioned: Term[];
}

interface SignificantTerms extends MentionedTerms {
  term: Term;
}

interface DatasetDiscovery {
  name: string;
  peopleMentioned: SignificantTerms[];
  companiesMentioned: SignificantTerms[];
  locationMentioned: SignificantTerms[];
  namesMentioned: SignificantTerms[];
}

interface CollectionDiscoveryModeProps {
  collectionId: string;
  model: any;
  discoveryResult?: DatasetDiscovery & {
    isPending?: boolean;
    isError?: boolean;
    shouldLoad?: boolean;
    error?: any;
  };
}

const CollectionDiscoveryMode: React.FC<CollectionDiscoveryModeProps> = ({
  model,
  discoveryResult,
}) => {
  const navigate = useNavigate();
  const location = useLocation();
  const isPending = discoveryResult?.isPending || false;
  const isError = discoveryResult?.isError || false;

  // The discovery data is directly on discoveryResult, not nested under .data
  const discovery = discoveryResult;
  const getSchemaForCategory = (category: string) => {
    switch (category.split('-')[0]) {
      case 'people':
        return 'Person';
      case 'companies':
        return 'Organization';
      case 'locations':
        return 'Address';
      default:
        return 'Thing';
    }
  };

  const handleTermClick = (termLabel: string, parentTerm?: Term) => {
    const quotedTerm = `"${termLabel}"`;
    let searchQuery = quotedTerm;

    // If this is a related term, include the parent term in the search
    if (parentTerm) {
      const quotedParentTerm = `"${parentTerm.label}"`;
      searchQuery = `${quotedParentTerm} ${quotedTerm}`;
    }

    const searchParams = new URLSearchParams(location.search);

    // Set collection search query parameter
    searchParams.set('csq', searchQuery);

    navigate({
      pathname: location.pathname,
      search: searchParams.toString(),
      hash: 'mode=search',
    });
  };

  const renderIcon = (schemaName: string) => {
    if (schemaName === 'Address')
      return (
        <Icon icon="home" className="CollectionDiscoveryMode__term-icon" />
      );
    const schema = model?.getSchema(schemaName);
    return (
      schema && (
        <Schema.Icon
          schema={schema}
          className="CollectionDiscoveryMode__term-icon"
        />
      )
    );
  };

  const renderTermCard = (term: Term, category: string, parentTerm?: Term) => {
    const schemaName = getSchemaForCategory(category);

    return (
      <div
        key={`${category}-${term.name}`}
        className="CollectionDiscoveryMode__term"
      >
        <div
          className="CollectionDiscoveryMode__term-item"
          onClick={() => handleTermClick(term.label, parentTerm)}
        >
          {renderIcon(schemaName)}
          <span className="CollectionDiscoveryMode__term-name">
            {term.label}
          </span>
          <span className="CollectionDiscoveryMode__term-count">
            ({term.count} times)
          </span>
        </div>
      </div>
    );
  };

  const renderRelatedTermCard = (
    term: Term,
    parentTerm: Term,
    category: string
  ) => {
    return renderTermCard(term, category, parentTerm);
  };

  const renderRelatedTermSection = (
    terms: Term[],
    parentTerm: Term,
    category: string,
    heading: string
  ) => {
    if (!terms || !terms.length) return null;
    return (
      <div className="CollectionDiscoveryMode__related-section">
        <div className="CollectionDiscoveryMode__related-label">{heading}</div>
        <div className="CollectionDiscoveryMode__related-items">
          {terms.map((term) =>
            renderRelatedTermCard(term, parentTerm, category)
          )}
        </div>
      </div>
    );
  };

  // Check if any significant term has related terms
  const hasRelatedTerms = (term: MentionedTerms) =>
    term.peopleMentioned.length > 0 ||
    term.companiesMentioned.length > 0 ||
    term.locationMentioned.length > 0 ||
    term.namesMentioned.length > 0;

  const renderSignificantTermsSection = (
    significantTerms: SignificantTerms[],
    title: string,
    category: string
  ) => {
    if (!significantTerms || significantTerms.length === 0) {
      return null;
    }

    if (!hasRelatedTerms) {
      return null;
    }

    const schemaName = getSchemaForCategory(category);

    return (
      <div className="CollectionDiscoveryMode__section">
        <H3 className="CollectionDiscoveryMode__section-title">
          <span className="CollectionDiscoveryMode__section-title-icon">
            {renderIcon(schemaName)}
          </span>
          {title}
        </H3>
        <div className="CollectionDiscoveryMode__significant-terms">
          {significantTerms.map(
            (sigTerm, index) =>
              hasRelatedTerms(sigTerm) && (
                <div
                  key={`${category}-${index}`}
                  className="CollectionDiscoveryMode__significant-term"
                >
                  <div className="CollectionDiscoveryMode__main-term">
                    <H4>{sigTerm.term.label}</H4>
                    The term {renderTermCard(sigTerm.term, `${category}-main`)}
                    occurs most frequently together with the names below. Click
                    on one term to search for it.
                  </div>
                  <div className="CollectionDiscoveryMode__related-terms">
                    {renderRelatedTermSection(
                      sigTerm.peopleMentioned,
                      sigTerm.term,
                      `people-${category}-${index}`,
                      'People'
                    )}
                    {renderRelatedTermSection(
                      sigTerm.companiesMentioned,
                      sigTerm.term,
                      `companies-${category}-${index}`,
                      'Companies & Organizations'
                    )}
                    {renderRelatedTermSection(
                      sigTerm.locationMentioned,
                      sigTerm.term,
                      `locations-${category}-${index}`,
                      'Locations'
                    )}
                    {renderRelatedTermSection(
                      sigTerm.namesMentioned,
                      sigTerm.term,
                      `names-${category}-${index}`,
                      'Other names'
                    )}
                  </div>
                </div>
              )
          )}
        </div>
      </div>
    );
  };

  const renderSkeleton = () => (
    <div className="CollectionDiscoveryMode">
      <div className="CollectionDiscoveryMode__header">
        <H3>Dataset Discovery Analysis</H3>
        <Spinner size={20} />
      </div>
      <div className="CollectionDiscoveryMode__content">
        {[...Array(4)].map((_, index) => (
          <div
            key={index}
            className={c('CollectionDiscoveryMode__section', Classes.SKELETON)}
          >
            <div
              className={c('CollectionDiscoveryMode__skeleton-block', 'CollectionDiscoveryMode__skeleton-block--sm')}
            />
            <div
              className={c('CollectionDiscoveryMode__skeleton-block', 'CollectionDiscoveryMode__skeleton-block--md')}
            />
          </div>
        ))}
      </div>
    </div>
  );

  if (isPending) {
    return renderSkeleton();
  }

  if (isError) {
    return <ErrorSection error={discoveryResult?.error} />;
  }

  if (!discovery || !discovery.name) {
    return (
      <div className="CollectionDiscoveryMode">
        <div className="CollectionDiscoveryMode__section">
          <H3>Dataset Discovery Analysis</H3>
          <p>No discovery analysis available for this collection.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="CollectionDiscoveryMode">
      <div className="CollectionDiscoveryMode__header">
        <p className="CollectionDiscoveryMode__description">
          Explore significant names and their relationships to other names
          within the collection. These names are extracted from the documents
          and other entities. Click on one term to search for it occurrences.
        </p>
      </div>

      <div className="CollectionDiscoveryMode__content">
        {renderSignificantTermsSection(
          discovery.peopleMentioned,
          'People',
          'people'
        )}

        {renderSignificantTermsSection(
          discovery.companiesMentioned,
          'Companies & Organizations',
          'companies'
        )}

        {renderSignificantTermsSection(
          discovery.locationMentioned,
          'Locations',
          'locations'
        )}

        {renderSignificantTermsSection(
          discovery.namesMentioned,
          'Other Names',
          'names'
        )}
      </div>
    </div>
  );
};

const mapStateToProps = (state: any, ownProps: { collectionId: string }) => ({
  discoveryResult: selectCollectionDiscovery(state, ownProps.collectionId),
  model: selectModel(state),
});

export default compose(connect(mapStateToProps))(CollectionDiscoveryMode);
