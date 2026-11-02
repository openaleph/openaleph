import React, { Component } from 'react';
import { FormattedMessage, defineMessages, injectIntl } from 'react-intl';
import { compose } from 'redux';
import { connect } from 'react-redux';

import withRouter from 'app/withRouter';
import Screen from 'components/Screen/Screen';
import Dashboard from 'components/Dashboard/Dashboard';
import CollectionIndex from 'components/CollectionIndex/CollectionIndex';
import InvestigationCreateButton from 'components/Toolbar/InvestigationCreateButton';
import { investigationsQuery } from 'queries';
import { selectInvestigationQuota, selectInvestigator } from 'selectors';

const messages = defineMessages({
  title: {
    id: 'cases.title',
    defaultMessage: 'Investigations',
  },
  empty: {
    id: 'cases.empty',
    defaultMessage: 'You do not have any investigations yet.',
  },
  create: {
    id: 'cases.create',
    defaultMessage: 'New investigation',
  },
  placeholder: {
    id: 'cases.placeholder',
    defaultMessage: 'Search investigations...',
  },
  no_results: {
    id: 'cases.no_results',
    defaultMessage: 'No investigations were found matching this query.',
  },
  not_investigator: {
    id: 'cases.not_allowed',
    defaultMessage:
      'You are not authorized to create new investigations. Contact your platform administrator.',
  },
  limit_reached: {
    id: 'cases.limit_reached',
    defaultMessage:
      'You have reached the maximum of {limit} investigations. Delete an existing investigation to create a new one.',
  },
});

export class InvestigationIndexScreen extends Component {
  render() {
    const { query, intl, canCreate, quota } = this.props;
    return (
      <Screen
        className="InvestigationIndexScreen"
        title={intl.formatMessage(messages.title)}
        requireSession
      >
        <Dashboard>
          <div className="Dashboard__title-container">
            <h5 className="Dashboard__title">
              {intl.formatMessage(messages.title)}
            </h5>
            <p className="Dashboard__subheading">
              <FormattedMessage
                id="case.description"
                defaultMessage="Investigations let you upload and share documents and data which belong to a particular story. You can upload PDFs, email archives or spreadsheets, and they will be made easy to search and browse."
              />
            </p>
            {!canCreate && (
              <p className="Dashboard__subheading">
                {intl.formatMessage(messages.not_investigator)}
              </p>
            )}
            {canCreate && quota.reached && (
              <p className="Dashboard__subheading">
                {intl.formatMessage(messages.limit_reached, {
                  limit: quota.limit,
                })}
              </p>
            )}
            {canCreate && !quota.reached && (
              <div className="Dashboard__actions">
                <InvestigationCreateButton
                  icon="briefcase"
                  text={intl.formatMessage(messages.create)}
                />
              </div>
            )}
          </div>
          <CollectionIndex
            query={query}
            icon="briefcase"
            placeholder={intl.formatMessage(messages.placeholder)}
            noResultsText={intl.formatMessage(messages.no_results)}
            emptyText={intl.formatMessage(messages.empty)}
          />
        </Dashboard>
      </Screen>
    );
  }
}

const mapStateToProps = (state, ownProps) => {
  const { location } = ownProps;
  return {
    query: investigationsQuery(location),
    canCreate: selectInvestigator(state),
    quota: selectInvestigationQuota(state),
  };
};

export default compose(
  withRouter,
  connect(mapStateToProps, {}),
  injectIntl
)(InvestigationIndexScreen);
