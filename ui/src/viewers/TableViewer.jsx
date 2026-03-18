import React, { Component } from 'react';
import { Cell, Column, Table, TruncatedFormat } from '@blueprintjs/table';
import { csvContextLoader } from 'components/common';

import './TableViewer.scss';

class TableViewer extends Component {
  constructor(props) {
    super(props);
    this.renderCell = this.renderCell.bind(this);
    this.onVisibleCellsChange = this.onVisibleCellsChange.bind(this);
  }

  componentDidUpdate(prevProps) {
    const initialDataLoad =
      prevProps.rows.length === 0 && this.props.rows.length !== 0;
    if (initialDataLoad) {
      this.forceUpdate();
    }
  }

  onVisibleCellsChange() {}

  renderCell(rowIndex, colIndex) {
    const { rows } = this.props;
    const row = rows[rowIndex];
    const value = row ? row[colIndex] : undefined;
    const loading = rowIndex >= rows.length;
    return (
      <Cell loading={loading}>
        <TruncatedFormat detectTruncation>{value || ''}</TruncatedFormat>
      </Cell>
    );
  }

  render() {
    const { columns, totalRowCount } = this.props;
    const hiddenRows = totalRowCount - 50;

    return (
      <div className="TableViewer">
        {hiddenRows > 0 && (
          <p className="TableViewer__hidden-rows">
            {hiddenRows.toLocaleString()} rows hidden, use Explore data to view all
          </p>
        )}
        <Table
          numRows={Math.min(totalRowCount, 50)}
          enableGhostCells
          enableRowHeader
          onVisibleCellsChange={this.onVisibleCellsChange}
        >
          {columns.map((column, i) => (
            <Column
              key={column}
              id={i}
              name={column}
              cellRenderer={this.renderCell}
            />
          ))}
        </Table>
      </div>
    );
  }
}

export default csvContextLoader(TableViewer, { maxRows: 50 });
