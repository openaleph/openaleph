import React from 'react';
import { connect } from 'react-redux';
import { defineMessages, injectIntl } from 'react-intl';
import { Button, Intent } from '@blueprintjs/core';
import { Tooltip2 as Tooltip } from '@blueprintjs/popover2';

import CreateInvestigationDialog from 'dialogs/CreateInvestigationDialog/CreateInvestigationDialog';
import { selectInvestigationQuota, selectSession } from 'selectors';

const messages = defineMessages({
  login: {
    id: 'case.create.login',
    defaultMessage: 'You must sign in to upload your own data.',
  },
  limit: {
    id: 'case.create.limit',
    defaultMessage: 'You have reached the maximum of {limit} investigations.',
  },
});

class InvestigationCreateButton extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      isOpen: false,
    };
    this.toggle = this.toggle.bind(this);
  }

  toggle() {
    this.setState(({ isOpen }) => ({ isOpen: !isOpen }));
  }

  render() {
    const { icon, intl, session, text, quota } = this.props;
    const buttonDisabled = !session.loggedIn || quota.reached;
    const tooltip = !session.loggedIn
      ? intl.formatMessage(messages.login)
      : intl.formatMessage(messages.limit, { limit: quota.limit });

    return (
      <>
        <Tooltip content={tooltip} disabled={!buttonDisabled}>
          <Button
            onClick={this.toggle}
            icon={icon}
            text={text}
            intent={Intent.PRIMARY}
            disabled={buttonDisabled}
          />
        </Tooltip>
        <CreateInvestigationDialog
          isOpen={this.state.isOpen}
          toggleDialog={this.toggle}
        />
      </>
    );
  }
}

const mapStateToProps = (state) => ({
  session: selectSession(state),
  quota: selectInvestigationQuota(state),
});

InvestigationCreateButton = connect(mapStateToProps)(InvestigationCreateButton);
InvestigationCreateButton = injectIntl(InvestigationCreateButton);
export default InvestigationCreateButton;
