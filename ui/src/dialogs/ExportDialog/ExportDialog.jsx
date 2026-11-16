import React, { Component } from 'react';
import {
  Button,
  Checkbox,
  Classes,
  Intent,
} from '@blueprintjs/core';
import { compose } from 'redux';
import { defineMessages, FormattedMessage, injectIntl } from 'react-intl';

import withRouter from 'app/withRouter';
import { showErrorToast, showSuccessToast } from 'src/app/toast';
import FormDialog from 'dialogs/common/FormDialog';

const messages = defineMessages({
  title: {
    id: 'exports.dialog.title',
    defaultMessage: 'Export search results',
  },
  button_confirm: {
    id: 'exports.dialog.confirm',
    defaultMessage: 'Export',
  },
  button_cancel: {
    id: 'exports.dialog.cancel',
    defaultMessage: 'Cancel',
  },
  export_success: {
    id: 'exports.dialog.success',
    defaultMessage: 'Your export has begun.',
  },
  dashboard_link: {
    id: 'exports.dialog.dashboard_link',
    defaultMessage: 'View progress',
  },
  type_results: {
    id: 'exports.dialog.type_results',
    defaultMessage: 'Results spreadsheet',
  },
  type_files: {
    id: 'exports.dialog.type_files',
    defaultMessage: 'Source files',
  },
  type_files_description: {
    id: 'exports.dialog.type_files_description',
    defaultMessage: 'ZIP archive of all matching documents',
  },
  type_results_description: {
    id: 'exports.dialog.type_results_description',
    defaultMessage: 'CSV with your search results',
  },
  type_entities: {
    id: 'exports.dialog.type_entities',
    defaultMessage: 'FtM entities',
  },
  type_entities_description: {
    id: 'exports.dialog.type_entities_description',
    defaultMessage: 'Structured entity data in FtM format',
  },
});

export class ExportDialog extends Component {
  constructor(props) {
    super(props);
    this.state = {
      files: false,
      results: true,
      entities: false,
      processing: false,
    };
    this.onExport = this.onExport.bind(this);
  }

  async onExport() {
    const { navigate, intl, onExport, toggleDialog } = this.props;
    const { files, results, entities } = this.state;
    const exportTypes = [
      files && 'files',
      results && 'results',
      entities && 'entities',
    ].filter(Boolean);

    this.setState({ processing: true });
    try {
      await onExport(exportTypes);
      showSuccessToast({
        message: intl.formatMessage(messages.export_success),
        action: {
          small: true,
          icon: 'share',
          text: intl.formatMessage(messages.dashboard_link),
          onClick: () => navigate('/exports'),
        },
      });
      toggleDialog();
    } catch (e) {
      showErrorToast(e);
    } finally {
      this.setState({ processing: false });
    }
  }

  render() {
    const { intl, isOpen, toggleDialog } = this.props;
    const { files, results, entities, processing } = this.state;
    const noneSelected = !files && !results && !entities;

    return (
      <FormDialog
        isOpen={isOpen}
        title={intl.formatMessage(messages.title)}
        icon="export"
        onClose={toggleDialog}
        processing={processing}
      >
        <div className={Classes.DIALOG_BODY}>
          <p className="ExportDialog__description">
            <FormattedMessage
              id="exports.dialog.description"
              defaultMessage="What do you want to include in your export?"
            />
          </p>
          <Checkbox
            checked={results}
            onChange={(e) => this.setState({ results: e.target.checked })}
            label={
              <>
                <strong>{intl.formatMessage(messages.type_results)}</strong>
                <span className="ExportDialog__type-description">
                  {' — '}
                  {intl.formatMessage(messages.type_results_description)}
                </span>
              </>
            }
          />
          <Checkbox
            checked={files}
            onChange={(e) => this.setState({ files: e.target.checked })}
            label={
              <>
                <strong>{intl.formatMessage(messages.type_files)}</strong>
                <span className="ExportDialog__type-description">
                  {' — '}
                  {intl.formatMessage(messages.type_files_description)}
                </span>
              </>
            }
          />
          <Checkbox
            checked={entities}
            onChange={(e) => this.setState({ entities: e.target.checked })}
            label={
              <>
                <strong>{intl.formatMessage(messages.type_entities)}</strong>
                <span className="ExportDialog__type-description">
                  {' — '}
                  {intl.formatMessage(messages.type_entities_description)}
                </span>
              </>
            }
          />
        </div>
        <div className={Classes.DIALOG_FOOTER}>
          <div className={Classes.DIALOG_FOOTER_ACTIONS}>
            <Button onClick={toggleDialog}>
              {intl.formatMessage(messages.button_cancel)}
            </Button>
            <Button
              intent={Intent.PRIMARY}
              onClick={this.onExport}
              disabled={noneSelected || processing}
            >
              {intl.formatMessage(messages.button_confirm)}
            </Button>
          </div>
        </div>
      </FormDialog>
    );
  }
}

export default compose(withRouter, injectIntl)(ExportDialog);
