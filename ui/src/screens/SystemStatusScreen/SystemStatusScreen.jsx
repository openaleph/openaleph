import React from 'react';
import { defineMessages, FormattedMessage, injectIntl } from 'react-intl';
import { compose } from 'redux';
import { connect } from 'react-redux';
import { Button, ProgressBar, Icon, Intent } from '@blueprintjs/core';
import { Tooltip2 as Tooltip } from '@blueprintjs/popover2';

import withRouter from 'app/withRouter';
import {
  Collection,
  ErrorSection,
  Numeric,
  RelativeTime,
  Skeleton,
} from 'components/common';
import Screen from 'components/Screen/Screen';
import Dashboard from 'components/Dashboard/Dashboard';
import ErrorScreen from 'components/Screen/ErrorScreen';
import { triggerCollectionCancel, fetchSystemStatus } from 'actions';
import { selectSystemStatus } from 'selectors';

import './SystemStatusScreen.scss';
import moment from 'moment';

const messages = defineMessages({
  title: {
    id: 'dashboard.title',
    defaultMessage: 'System Status',
  },
  no_active: {
    id: 'collection.status.no_active',
    defaultMessage: 'There are no ongoing tasks',
  },
  cancel_button: {
    id: 'collection.status.cancel_button',
    defaultMessage: 'Cancel the process',
  },
});

const LABELS = {
  ingest: 'Import source documents',
  analyze: 'Analyze and extract',
  index_entities: 'Index entities',
  transcribe: 'Speech to text',
  geocode: 'Geocode addresses',
};

const ICONS = {
  ingest: 'add-to-folder',
  analyze: 'predictive-analysis',
  index_entities: 'database',
  transcribe: 'volume-up',
  geocode: 'geosearch',
};

export class SystemStatusScreen extends React.Component {
  constructor(props) {
    super(props);
    this.renderRow = this.renderRow.bind(this);
    this.fetchStatus = this.fetchStatus.bind(this);
    this.cancelCollection = this.cancelCollection.bind(this);
  }

  componentDidMount() {
    this.fetchStatus();
  }

  componentDidUpdate() {
    const { result } = this.props;
    if (result.shouldLoad) {
      this.fetchStatus();
    }
  }

  cancelAll() {
    if (this.loadPromise?.cancel) {
      this.loadPromise.cancel();
      this.loadPromise = undefined;
    }
    clearTimeout(this.timeout);
  }

  componentWillUnmount() {
    this.cancelAll();
  }

  fetchStatus() {
    this.cancelAll();
    this.loadPromise = this.props.fetchSystemStatus();
    this.loadPromise.finally(() => {
      this.timeout = setTimeout(this.fetchStatus, 10000);
    });
  }

  async cancelCollection(collection) {
    await this.props.triggerCollectionCancel(collection.id);
    this.fetchStatus();
  }

  renderRowSkeleton = (item) => (
    <tr key={item}>
      <td className="entity">
        <Skeleton.Text type="span" length={30} />
      </td>
      <td className="numeric narrow">
        <Skeleton.Text type="span" length={1} />
      </td>
      <td className="numeric narrow">
        <Skeleton.Text type="span" length={1} />
      </td>
      <td className="numeric narrow">
        <Skeleton.Text type="span" length={1} />
      </td>
      <td>
        <Skeleton.Text type="span" length={15} />
      </td>
      <td className="numeric narrow">
        <Skeleton.Text type="span" length={1} />
      </td>
      <td className="numeric narrow">
        <Skeleton.Text type="span" length={1} />
      </td>
      <td className="numeric narrow">
        <Skeleton.Text type="span" length={1} />
      </td>
      <td className="numeric narrow">
        <Skeleton.Text type="span" length={10} />
      </td>
    </tr>
  );

  renderSectionLabel(sectionName, collection, batch, queue, task) {
    if (!!collection) {
      return <Collection.Link collection={collection} />;
    }
    if (sectionName === '__system__') {
      return (
        <FormattedMessage
          id="status.no_collection"
          defaultMessage="System tasks"
        />
      );
    }
    const name = sectionName.split('.').pop();
    const cancel = name === 'cancel_dataset';
    let label = LABELS[name] || sectionName;
    let icon = ICONS[name];
    if (cancel) {
      label = 'Cancelling...';
      icon = 'cross-circle';
    }
    return (
      <div style={{ marginLeft: 25 }}>
        {icon && (
          <Icon icon={icon} intent={cancel ? Intent.DANGER : Intent.NONE} />
        )}
        <span style={{ marginLeft: icon ? 10 : 0, fontWeight: 'normal' }}>
          {label}{' '}
        </span>
        {cancel && (
          <span>
            {' '}
            Waiting for current running tasks to finish and clean up.
          </span>
        )}
        {queue && task && (
          <span
            style={{ display: 'block', fontWeight: 'normal', color: 'gray' }}
          >
            <code>{queue}::{task}</code>
          </span>
        )}
      </div>
    );
  }

  renderRow(res, section, batch, queue, task) {
    if (!res.active) return null;
    const { intl } = this.props;
    const { collection } = res;
    const progress = res.finished / res.total;
    const startedAt = new Date(res.min_ts);
    const duration = moment.duration(res.remaining_time);
    return (
      <>
        <tr key={collection?.id || `${section}-${res.name}`}>
          <td className="entity">
            {this.renderSectionLabel(res.name, collection, batch, queue, task)}
          </td>
          <td>
            <RelativeTime date={startedAt} />
          </td>
          <td>
            {section === 'collection' ? null : `in ${duration.humanize()}`}
          </td>
          <td className="numeric narrow">{res.doing}</td>
          <td>
            <ProgressBar value={progress} intent={Intent.PRIMARY} />
          </td>
          <td className="numeric narrow">
            <Numeric num={res.finished} />
          </td>
          <td className="numeric narrow">
            <Numeric num={res.active} />
          </td>
          <td className="numeric narrow">
            <Numeric num={res.failed} />
          </td>
          <td className="numeric narrow">
            {collection && collection.writeable && (
              <Tooltip content={intl.formatMessage(messages.cancel_button)}>
                <Button
                  onClick={() => this.cancelCollection(collection)}
                  icon="delete"
                  minimal
                  small
                >
                  <FormattedMessage
                    id="collection.cancel.button"
                    defaultMessage="Cancel"
                  />
                </Button>
              </Tooltip>
            )}
          </td>
        </tr>
        {section === 'collection' &&
          res.batches.map((b) =>
            b.queues.map((q) =>
              q.tasks.map((t) =>
                this.renderRow(t, 'task', b.name, q.name, t.name)
              )
            )
          )}
      </>
    );
  }

  render() {
    const { result, intl } = this.props;
    if (result.isError) {
      return <ErrorScreen error={result.error} />;
    }
    const results = result.results || [];
    const skeletonItems = [...Array(15).keys()];

    return (
      <Screen title={intl.formatMessage(messages.title)} requireSession>
        <Dashboard>
          <>
            <div className="Dashboard__title-container">
              <h5 className="Dashboard__title">
                {intl.formatMessage(messages.title)}
              </h5>
              <p className="Dashboard__subheading">
                <FormattedMessage
                  id="dashboard.subheading"
                  defaultMessage="Check the progress of ongoing data analysis, upload, and processing tasks."
                />
              </p>
            </div>
            {result.total === 0 && (
              <ErrorSection
                icon="dashboard"
                title={intl.formatMessage(messages.no_active)}
              />
            )}
            {result.total !== 0 && (
              <table className="StatusTable">
                <thead>
                  <tr>
                    <th>
                      <FormattedMessage
                        id="collection.status.collection"
                        defaultMessage="Dataset"
                      />
                    </th>
                    <th>
                      <FormattedMessage
                        id="collection.status.started"
                        defaultMessage="Started"
                      />
                    </th>
                    <th>
                      <FormattedMessage
                        id="collection.status.remaining_time"
                        defaultMessage="Expected finish"
                      />
                    </th>
                    <th className="numeric narrow">
                      <FormattedMessage
                        id="collection.status.running"
                        defaultMessage="Running"
                      />
                    </th>
                    <th>
                      <FormattedMessage
                        id="collection.status.progress"
                        defaultMessage="Progress"
                      />
                    </th>
                    <th className="numeric narrow">
                      <FormattedMessage
                        id="collection.status.finished_tasks"
                        defaultMessage="Finished"
                      />
                    </th>
                    <th className="numeric narrow">
                      <FormattedMessage
                        id="collection.status.pending_tasks"
                        defaultMessage="Pending"
                      />
                    </th>
                    <th className="numeric narrow">
                      <FormattedMessage
                        id="collection.status.errors"
                        defaultMessage="Errors"
                      />
                    </th>
                    <th className="numeric narrow" />
                  </tr>
                </thead>
                <tbody>
                  {results.map((r) => this.renderRow(r, 'collection'))}
                  {result.total === undefined &&
                    skeletonItems.map(this.renderRowSkeleton)}
                </tbody>
              </table>
            )}
          </>
        </Dashboard>
      </Screen>
    );
  }
}

const mapStateToProps = (state) => {
  const status = selectSystemStatus(state);
  return { result: status };
};

export default compose(
  withRouter,
  connect(mapStateToProps, { triggerCollectionCancel, fetchSystemStatus }),
  injectIntl
)(SystemStatusScreen);
