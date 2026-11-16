import React, { PureComponent } from 'react';
import c from 'classnames';
import { Button, Intent, Alert } from '@blueprintjs/core';

import {
  Skeleton,
  ExportLink,
  FileSize,
  RelativeTime,
} from 'src/components/common';

import './Export.scss';

class Export extends PureComponent {
  constructor(props) {
    super(props);
    this.state = {
      showDeleteConfirm: false,
    };
  }

  handleDeleteClick = () => {
    this.setState({ showDeleteConfirm: true });
  };

  handleDeleteConfirm = () => {
    const { export_, onDelete } = this.props;
    if (onDelete) {
      onDelete(export_.id);
    }
    this.setState({ showDeleteConfirm: false });
  };

  handleDeleteCancel = () => {
    this.setState({ showDeleteConfirm: false });
  };

  renderSkeleton = () => (
    <tr className="Export nowrap">
      <td className="export-label wide">
        <Skeleton.Text type="span" length={15} />
      </td>
      <td className="export-filesize">
        <Skeleton.Text type="span" length={5} />
      </td>
      <td className="export-status">
        <Skeleton.Text type="span" length={5} />
      </td>
      <td className="timestamp">
        <Skeleton.Text type="span" length={15} />
      </td>
      <td className="export-actions">
        <Skeleton.Text type="span" length={5} />
      </td>
    </tr>
  );

  render() {
    const { isPending, export_ } = this.props;
    const { showDeleteConfirm } = this.state;

    if (isPending) {
      return this.renderSkeleton();
    }

    const { id, created_at: createdAt, export_status: status } = export_;

    return (
      <>
        <tr key={id} className={c('Export nowrap', status)}>
          <td className="export-label wide">
            {export_.meta?.no_files ? (
              <span className="export-warning no-files">
                No downloadable files found
              </span>
            ) : export_.meta?.too_large ? (
              <span className="export-warning too-large">
                Export too large - contact administrator
              </span>
            ) : (
              <ExportLink export_={export_} />
            )}
          </td>
          <td className="export-filesize">
            <FileSize value={export_.file_size} />
          </td>
          <td className="export-status">{export_.status}</td>
          <td className="timestamp">
            <RelativeTime utcDate={createdAt} />
          </td>
          <td className="export-actions">
            <Button
              minimal
              small
              icon="trash"
              intent={Intent.DANGER}
              onClick={this.handleDeleteClick}
              title="Delete export"
            />
          </td>
        </tr>
        <Alert
          isOpen={showDeleteConfirm}
          confirmButtonText="Delete"
          cancelButtonText="Cancel"
          intent={Intent.DANGER}
          icon="trash"
          onConfirm={this.handleDeleteConfirm}
          onCancel={this.handleDeleteCancel}
        >
          <p>Are you sure you want to remove this export? This cannot be undone.</p>
        </Alert>
      </>
    );
  }
}

export default Export;
