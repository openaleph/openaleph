import React, { Component } from 'react';
import { defineMessages, FormattedMessage, injectIntl } from 'react-intl';
import { compose } from 'redux';
import { connect } from 'react-redux';
import { Collapse, Icon } from '@blueprintjs/core';

import withRouter from 'app/withRouter';
import { ErrorSection } from 'src/components/common';
import { selectExports } from 'selectors';
import { fetchExports, deleteExport } from 'src/actions';
import Export from 'src/components/Exports/Export';

import './ExportsList.scss';

const messages = defineMessages({
  no_exports: {
    id: 'exports.no_exports',
    defaultMessage: 'You have no exports to download',
  },
});

class ExportsList extends Component {
  constructor(props) {
    super(props);
    this._pollInterval = null;
    this.state = {
      openGroups: new Set(),
    };
  }

  componentDidMount() {
    this.props.fetchExports();
    this._startPollingIfNeeded();
  }

  componentDidUpdate(prevProps) {
    const hadPending = this._hasPendingExports(prevProps.exports);
    const hasPending = this._hasPendingExports(this.props.exports);
    
    // Keep all groups closed by default - remove auto-opening
    
    if (!hadPending && hasPending) {
      this._startPollingIfNeeded();
    } else if (hadPending && !hasPending) {
      this._stopPolling();
    }
  }

  componentWillUnmount() {
    this._stopPolling();
  }

  handleDeleteExport = async (exportId) => {
    await this.props.deleteExport(exportId);
    // Refresh the exports list after deletion
    this.props.fetchExports();
  };

  _hasPendingExports(exports) {
    return !!(
      exports.results && exports.results.some((e) => e.status === 'pending')
    );
  }

  _startPollingIfNeeded() {
    if (this._pollInterval) return;
    this._pollInterval = setInterval(() => {
      if (this._hasPendingExports(this.props.exports)) {
        this.props.fetchExports();
      } else {
        this._stopPolling();
      }
    }, 5000);
  }

  _stopPolling() {
    if (this._pollInterval) {
      clearInterval(this._pollInterval);
      this._pollInterval = null;
    }
  }

  groupExportsBySearchTerm = (exports) => {
    const groups = {};
    exports.forEach(export_ => {
      const searchTerm = export_.meta?.search_term || 'All results';
      if (!groups[searchTerm]) {
        groups[searchTerm] = [];
      }
      groups[searchTerm].push(export_);
    });
    
    // Sort each group by creation date (newest first)
    Object.keys(groups).forEach(key => {
      groups[key].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    });
    
    return groups;
  };

  getExportTypeSummary = (groupExports) => {
    const types = {};
    groupExports.forEach(export_ => {
      const operation = export_.operation;
      let type = 'Unknown';
      if (operation === 'exportfiles') type = 'Files';
      else if (operation === 'exportcsv') type = 'CSV';
      else if (operation === 'exportentities') type = 'Entities';
      else if (operation === 'exportjsonl') type = 'JSONL';
      
      types[type] = (types[type] || 0) + 1;
    });
    
    const typesList = Object.entries(types)
      .map(([type, count]) => count > 1 ? `${count} ${type}` : type);
    
    return typesList.join(', ');
  };

  toggleGroup = (searchTerm) => {
    const newOpenGroups = new Set(this.state.openGroups);
    if (newOpenGroups.has(searchTerm)) {
      newOpenGroups.delete(searchTerm);
    } else {
      newOpenGroups.add(searchTerm);
    }
    this.setState({ openGroups: newOpenGroups });
  };

  render() {
    const { exports, intl } = this.props;
    const skeletonItems = [...Array(15).keys()];

    if (exports.total === 0) {
      return (
        <ErrorSection
          icon="export"
          title={intl.formatMessage(messages.no_exports)}
        />
      );
    }

    const groups = exports.results ? this.groupExportsBySearchTerm(exports.results) : {};
    // Sort groups chronologically by newest export in each group
    const groupNames = Object.keys(groups).sort((a, b) => {
      const aNewest = groups[a][0];
      const bNewest = groups[b][0];
      return new Date(bNewest.created_at) - new Date(aNewest.created_at);
    });

    return (
      <>
        {groupNames.map(searchTerm => {
          const groupExports = groups[searchTerm];
          const isOpen = this.state.openGroups.has(searchTerm);
          const newestExport = groupExports[0];
          
          return (
            <div key={searchTerm} className="ExportGroup">
              <div 
                className={`ExportGroup__header ${isOpen ? 'ExportGroup__header--open' : ''}`}
                onClick={() => this.toggleGroup(searchTerm)}
              >
                <Icon 
                  icon={isOpen ? 'chevron-down' : 'chevron-right'} 
                  className="ExportGroup__chevron"
                />
                <div>
                  <div className="ExportGroup__title">{searchTerm}</div>
                  <div className="ExportGroup__subtitle">
                    Created {newestExport && <span>{new Date(newestExport.created_at).toLocaleDateString()}</span>}
                    • {this.getExportTypeSummary(groupExports)}
                  </div>
                </div>
              </div>
              <Collapse isOpen={isOpen}>
                <table className="ExportsTable data-table">
                  <thead>
                    <tr>
                      <th className="wide">
                        <FormattedMessage id="exports.name" defaultMessage="Name" />
                      </th>
                      <th>
                        <FormattedMessage id="exports.size" defaultMessage="Size" />
                      </th>
                      <th>
                        <FormattedMessage id="exports.status" defaultMessage="Status" />
                      </th>
                      <th>
                        <FormattedMessage
                          id="exports.created"
                          defaultMessage="Created"
                        />
                      </th>
                      <th>
                        <FormattedMessage
                          id="exports.actions"
                          defaultMessage="Actions"
                        />
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {groupExports.map((export_) => (
                      <Export key={export_.id} export_={export_} onDelete={this.handleDeleteExport} />
                    ))}
                  </tbody>
                </table>
              </Collapse>
            </div>
          );
        })}
        
        {exports.isPending && (
          <div className="ExportGroup">
            <div className="ExportGroup__header ExportGroup__header--loading">
              <div className="ExportGroup__title">Loading exports...</div>
            </div>
            <table className="ExportsTable data-table">
              <tbody>
                {skeletonItems.map((item) => <Export key={item} isPending />)}
              </tbody>
            </table>
          </div>
        )}
      </>
    );
  }
}

const mapStateToProps = (state) => ({
  exports: selectExports(state),
});

const mapDispatchToProps = {
  fetchExports,
  deleteExport,
};

export default compose(
  withRouter,
  connect(mapStateToProps, mapDispatchToProps),
  injectIntl
)(ExportsList);
