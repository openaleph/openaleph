// In-browser CSV explorer for Table documents. Loads the CSV into a SQLite
// database via a web worker (sql.js + papaparse), then runs search, filter,
// sort and pagination queries against it without any server round-trips.
// Requires public/sql-wasm.wasm (copied from node_modules/sql.js/dist/).
import React, { Component } from 'react';
import { Button, Checkbox, Spinner, NonIdealState, Popover, Position } from '@blueprintjs/core';
import { defineMessages, injectIntl, FormattedMessage } from 'react-intl';

import './CSVExplorer.scss';

const PAGE_SIZE = 100;

const messages = defineMessages({
  search_placeholder: {
    id: 'document.csv_explorer.search',
    defaultMessage: 'Search…',
  },
  filter_column_placeholder: {
    id: 'document.csv_explorer.filter_column',
    defaultMessage: '- column -',
  },
  filter_apply: {
    id: 'document.csv_explorer.filter_apply',
    defaultMessage: 'Apply',
  },
});

class CSVExplorer extends Component {
  constructor(props) {
    super(props);
    this.state = {
      skiprows: 0,
      genericHeaders: false,
      separator: 'auto',
      loading: false,
      error: null,
      columns: [],
      rows: [],
      total: 0,
      search: '',
      filters: {},
      sortCol: null,
      sortDir: 'ASC',
      page: 1,
      filterCol: '',
      filterOp: 'contains',
      filterVal: '',
    };
    this.worker = null;
    this.onSearch = this.onSearch.bind(this);
    this.onSort = this.onSort.bind(this);
    this.onPage = this.onPage.bind(this);
    this.onApplyFilter = this.onApplyFilter.bind(this);
  }

  componentDidMount() {
    this.initWorker();
  }

  componentWillUnmount() {
    if (this.worker) this.worker.terminate();
  }

  initWorker() {
    const { document } = this.props;
    const { skiprows, genericHeaders, separator } = this.state;

    if (this.worker) this.worker.terminate();

    this.setState({ loading: true, error: null, columns: [], rows: [], total: 0 });

    this.worker = new Worker(new URL('../util/sqlWorker.js', import.meta.url));

    this.worker.onmessage = (event) => {
      const { type } = event.data;
      if (type === 'ready') {
        const { columns, total, delimiter } = event.data;
        const separatorUpdate = this.state.separator === 'auto' ? { separator: delimiter } : {};
        this.setState({ columns, total, loading: false, ...separatorUpdate }, () => {
          this.runQuery();
        });
      } else if (type === 'results') {
        this.setState({ rows: event.data.rows, total: event.data.total });
      } else if (type === 'error') {
        this.setState({ error: event.data.message, loading: false });
      }
    };

    this.worker.postMessage({
      type: 'init',
      csvUrl: document.links.file || document.links.csv,
      skiprows,
      genericHeaders,
      separator,
    });
  }

  runQuery() {
    const { search, filters, sortCol, sortDir, page } = this.state;
    this.worker.postMessage({
      type: 'query',
      search,
      filters,
      sortCol,
      sortDir,
      page,
      pageSize: PAGE_SIZE,
    });
  }

  onSearch(e) {
    this.setState({ search: e.target.value, page: 1 }, () => this.runQuery());
  }

  onSort(col) {
    this.setState(({ sortCol, sortDir }) => ({
      sortCol: col,
      sortDir: sortCol === col && sortDir === 'ASC' ? 'DESC' : 'ASC',
      page: 1,
    }), () => this.runQuery());
  }

  onPage(page) {
    this.setState({ page }, () => this.runQuery());
  }

  onApplyFilter() {
    const { filterCol, filterOp, filterVal, filters } = this.state;
    if (!filterCol) return;
    const newFilters = { ...filters, [filterCol]: { op: filterOp, val: filterVal } };
    this.setState({ filters: newFilters, page: 1 }, () => this.runQuery());
  }

  onSettingsChange(patch) {
    this.setState(patch, () => this.initWorker());
  }

  renderSettings() {
    const { skiprows, genericHeaders, separator } = this.state;

    return (
      <div className="CSVExplorer__settings-popover">
        <label>
          <span>Skip rows</span>
          <input
            className="bp4-input bp4-small"
            type="number"
            min={0}
            value={skiprows}
            disabled={genericHeaders}
            onChange={(e) => this.onSettingsChange({ skiprows: parseInt(e.target.value) || 0 })}
          />
        </label>
        <label>
          <span>Separator</span>
          <div className="bp4-html-select bp4-small">
            <select value={separator} onChange={(e) => this.onSettingsChange({ separator: e.target.value })}>
              <option value="auto">auto</option>
              <option value=",">,</option>
              <option value=";">;</option>
              <option value=":">:</option>
              <option value="\t">tab</option>
              <option value="|">|</option>
            </select>
            <span className="bp4-icon bp4-icon-double-caret-vertical" />
          </div>
        </label>
        <Checkbox
          checked={genericHeaders}
          label="Generic headers"
          onChange={(e) => this.onSettingsChange({ genericHeaders: e.target.checked })}
        />
      </div>
    );
  }

  renderToolbar() {
    const { intl } = this.props;
    const { search, total } = this.state;

    return (
      <div className="CSVExplorer__toolbar">
        <input
          className="bp4-input"
          type="search"
          placeholder={intl.formatMessage(messages.search_placeholder)}
          value={search}
          onChange={this.onSearch}
        />
        <span className="CSVExplorer__count">
          {total.toLocaleString()} rows
        </span>
        <Popover
          content={this.renderSettings()}
          position={Position.BOTTOM_RIGHT}
          minimal
        >
          <Button minimal icon="cog" />
        </Popover>
      </div>
    );
  }

  renderFilterBar() {
    const { intl } = this.props;
    const { columns, filterCol, filterOp, filterVal, filters } = this.state;
    const activeFilters = Object.entries(filters);

    return (
      <div className="CSVExplorer__filterbar">
        <div className="CSVExplorer__filterbar-row">
          <div className="bp4-html-select bp4-small">
            <select value={filterCol} onChange={(e) => this.setState({ filterCol: e.target.value })}>
              <option value="">{intl.formatMessage(messages.filter_column_placeholder)}</option>
              {columns.map((col, i) => (
                <option key={i} value={col}>{col}</option>
              ))}
            </select>
            <span className="bp4-icon bp4-icon-double-caret-vertical" />
          </div>
          <div className="bp4-html-select bp4-small">
            <select value={filterOp} onChange={(e) => this.setState({ filterOp: e.target.value })}>
              <option value="contains">contains</option>
              <option value="not_contains">not contains</option>
              <option value="equals">=</option>
              <option value="starts">starts with</option>
              <option value="ends">ends with</option>
              <option value="lt">&lt;</option>
              <option value="gt">&gt;</option>
            </select>
            <span className="bp4-icon bp4-icon-double-caret-vertical" />
          </div>
          <input
            className="bp4-input bp4-small"
            type="text"
            value={filterVal}
            onChange={(e) => this.setState({ filterVal: e.target.value })}
            onKeyDown={(e) => e.key === 'Enter' && this.onApplyFilter()}
          />
          <Button small intent="primary" onClick={this.onApplyFilter}>
            <FormattedMessage {...messages.filter_apply} />
          </Button>
        </div>
        {activeFilters.length > 0 && (
          <div className="CSVExplorer__filterbar-tags">
            {activeFilters.map(([col, { op, val }]) => (
              <span key={col} className="CSVExplorer__filter-tag">
                <strong>{col}</strong> {({ contains: 'contains', not_contains: 'not contains', equals: '=', starts: 'starts with', ends: 'ends with', lt: '<', gt: '>' })[op]} "{val}"
                <button
                  onClick={() => {
                    const { [col]: _removed, ...rest } = this.state.filters;
                    this.setState({ filters: rest, page: 1 }, () => this.runQuery());
                  }}
                >×</button>
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }

  render() {
    const { loading, error, columns, rows, sortCol, sortDir, page, total } = this.state;
    const totalPages = Math.ceil(total / PAGE_SIZE);

    if (error) {
      return <NonIdealState icon="error" title="Error" description={error} />;
    }

    return (
      <div className="CSVExplorer__table-container">
        {this.renderToolbar()}
        {columns.length > 0 && this.renderFilterBar()}
        {loading && (
          <NonIdealState icon={<Spinner />} title="Loading…" />
        )}
        {!loading && columns.length > 0 && (
          <>
            <div className="CSVExplorer__scroll">
              <table className="CSVExplorer__table">
                <thead>
                  <tr>
                    {columns.map((col, i) => (
                      <th
                        key={i}
                        onClick={() => this.onSort(col)}
                        className={sortCol === col ? `sorted-${sortDir.toLowerCase()}` : ''}
                      >
                        {col}
                        {sortCol === col && (sortDir === 'ASC' ? ' ↑' : ' ↓')}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => (
                    <tr key={i}>
                      {row.map((cell, j) => (
                        <td key={j}>{cell}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {totalPages > 1 && (
              <div className="CSVExplorer__pagination">
                <Button minimal small disabled={page === 1} onClick={() => this.onPage(page - 1)} icon="chevron-left" />
                <span>{page} / {totalPages}</span>
                <Button minimal small disabled={page === totalPages} onClick={() => this.onPage(page + 1)} icon="chevron-right" />
              </div>
            )}
          </>
        )}
      </div>
    );
  }
}

export default injectIntl(CSVExplorer);
