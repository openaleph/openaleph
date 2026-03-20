import React from 'react';
import { FormattedMessage } from 'react-intl';
import { Tab, Tabs, Icon } from '@blueprintjs/core';
import queryString from 'query-string';
import { compose } from 'redux';
import { connect } from 'react-redux';

import withRouter from 'app/withRouter';
import {
  Count,
  Property,
  ResultCount,
  Schema,
  SectionLoading,
  TextLoading,
} from 'components/common';
import {
  canonicalSimilarQuery,
  canonicalReferenceQuery,
} from 'queries';
import {
  selectCanonicalReferences,
  selectCanonicalReference,
  selectCanonicalTags,
  selectSimilarResult,
} from 'selectors';
import EntityReferencesMode from 'components/Entity/EntityReferencesMode';
import ProfileSimilarMode from 'components/Profile/ProfileSimilarMode';
import ProfileItemsMode from './ProfileItemsMode';
import ProfileProvenanceMode from './ProfileProvenanceMode';

class ProfileViews extends React.Component {
  constructor(props) {
    super(props);
    this.handleTabChange = this.handleTabChange.bind(this);
  }

  handleTabChange(mode) {
    const { navigate, location } = this.props;
    const parsedHash = queryString.parse(location.hash);
    parsedHash.mode = mode;
    navigate({
      pathname: location.pathname,
      search: location.search,
      hash: queryString.stringify(parsedHash),
    });
  }

  render() {
    const {
      activeMode,
      canonical,
      references,
      similar,
      reference,
      referenceQuery,
      viaEntityId,
    } = this.props;
    if (references.total === undefined) {
      return <SectionLoading />;
    }

    return (
      <Tabs
        id="ProfileInfoTabs"
        onChange={this.handleTabChange}
        selectedTabId={activeMode}
        renderActiveTabPanelOnly
        className="info-tabs-padding"
      >
        <Tab
          id="items"
          title={
            <>
              <Icon icon="layers" className="left-icon" />
              <FormattedMessage
                id="profile.info.items"
                defaultMessage="Entity decisions"
              />
              <Count count={canonical?.entities?.length || 0} />
            </>
          }
          panel={
            <ProfileItemsMode canonical={canonical} viaEntityId={viaEntityId} />
          }
        />
        <Tab
          id="provenance"
          title={
            <>
              <Icon icon="document-open" className="left-icon" />
              <FormattedMessage
                id="profile.info.provenance"
                defaultMessage="Data Lineage"
              />
            </>
          }
          panel={<ProfileProvenanceMode canonical={canonical} />}
        />
        <Tab
          id="similar"
          disabled={similar.total === 0}
          title={
            <TextLoading loading={similar.total === undefined}>
              <Icon icon="layer-outline" className="left-icon" />
              <FormattedMessage
                id="profile.info.similar"
                defaultMessage="Suggested"
              />
              <ResultCount result={similar} />
            </TextLoading>
          }
          panel={<ProfileSimilarMode canonical={canonical} />}
        />
        {references.results.map((ref) => (
          <Tab
            id={ref.property.qname}
            key={ref.property.qname}
            title={
              <>
                <Schema.Icon schema={ref.schema} className="left-icon" />
                <Property.Reverse prop={ref.property} />
                <Count count={ref.count} />
              </>
            }
            panel={
              <EntityReferencesMode
                entity={canonical.entity}
                mode={activeMode}
                reference={reference}
                query={referenceQuery}
              />
            }
          />
        ))}
        {!references.total && references.isPending && (
          <Tab id="loading" title={<TextLoading loading={true} />} />
        )}
      </Tabs>
    );
  }
}

const mapStateToProps = (state, ownProps) => {
  const { canonical, location, activeMode } = ownProps;
  const reference = selectCanonicalReference(state, canonical.id, activeMode);
  return {
    reference,
    references: selectCanonicalReferences(state, canonical.id),
    referenceQuery: canonicalReferenceQuery(location, canonical, reference),
    tags: selectCanonicalTags(state, canonical.id),
    similar: selectSimilarResult(
      state,
      canonicalSimilarQuery(location, canonical.id)
    ),
  };
};

export default compose(withRouter, connect(mapStateToProps))(ProfileViews);
