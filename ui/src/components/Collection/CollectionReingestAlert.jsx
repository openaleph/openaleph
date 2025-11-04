import React, { Component } from 'react';
import { defineMessages, FormattedMessage, injectIntl } from 'react-intl';
import { Alert, Intent } from '@blueprintjs/core';
import { compose } from 'redux';
import { connect } from 'react-redux';
import { triggerCollectionReingest } from 'actions';
import { showSuccessToast } from 'app/toast';
import { Collection } from 'components/common';

const messages = defineMessages({
  processing: {
    id: 'collection.reingest.processing',
    defaultMessage: 'Re-ingest started.',
  },
  cancel: {
    id: 'collection.analyze.cancel',
    defaultMessage: 'Cancel',
  },
  confirm: {
    id: 'collection.reingest.confirm',
    defaultMessage: 'Start processing',
  },
});

class CollectionReingestAlert extends Component {
  constructor(props) {
    super(props);
    this.onConfirm = this.onConfirm.bind(this);
  }

  onConfirm() {
    const { collection, intl } = this.props;
    this.props.triggerCollectionReingest(collection.id);
    showSuccessToast(intl.formatMessage(messages.processing));
    this.props.toggleDialog();
  }

  render() {
    const { collection, intl, isOpen } = this.props;
    return (
      <Alert
        cancelButtonText={intl.formatMessage(messages.cancel)}
        confirmButtonText={intl.formatMessage(messages.confirm)}
        canEscapeKeyCancel
        canOutsideClickCancel
        icon="automatic-updates"
        intent={Intent.DANGER}
        isOpen={isOpen}
        onCancel={this.props.toggleDialog}
        onConfirm={this.onConfirm}
      >
        <p>
          <FormattedMessage
            id="collection.reingest.text"
            defaultMessage="You're about to re-process all documents in {collectionLabel}. This might take some time."
            values={{
              collectionLabel: (
                <Collection.Label collection={collection} icon={false} />
              ),
            }}
          />
        </p>
      </Alert>
    );
  }
}

export default compose(
  connect(null, { triggerCollectionReingest }),
  injectIntl
)(CollectionReingestAlert);
