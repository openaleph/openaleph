/* eslint-disable */
import initSqlJs from 'sql.js';
import Papa from 'papaparse';

let db = null;
let columns = [];     // display names (original, may have duplicates)
let colAliases = [];  // internal SQLite names: c0, c1, c2, ...
let csvText = null;
let currentSettings = {};

async function init(csvUrl, skiprows, genericHeaders, separator) {
  if (!csvText || currentSettings.csvUrl !== csvUrl) {
    const response = await fetch(csvUrl);
    csvText = await response.text();
  }
  currentSettings = { csvUrl, skiprows, genericHeaders, separator };
  await processCSV();
}

async function processCSV() {
  const { skiprows, genericHeaders, separator } = currentSettings;
  const SQL = await initSqlJs({ locateFile: () => '/sql-wasm.wasm' });
  db = new SQL.Database();

  const lines = csvText.split(/\r?\n/);
  // I could not get papaparse skipFirstNLines to do anything
  const csv = (skiprows > 0 ? lines.slice(skiprows) : lines).join('\n');

  const parsed = Papa.parse(csv, {
    dynamicTyping: true,
    skipEmptyLines: 'greedy',
    delimiter: separator === 'auto' ? '' : separator,
    delimitersToGuess: separator === 'auto' ? [',', '\t', '|', ';'] : undefined,
    transform: function(value) {
    if (value != null && typeof value === 'string') {
      const trimmed = value.trim();
      const euroRegex = /^[+-]?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?$/;

      if (euroRegex.test(trimmed)) {
        return trimmed
          .replace(/\./g, '')
          .replace(',', '.');
      }
    }
    return value;
  }
  });

  if (!parsed.data.length) {
    self.postMessage({ type: 'error', message: 'No data found in CSV' });
    return;
  }

  if (genericHeaders) {
    columns = parsed.data[0].map((_, i) => `col${i + 1}`);
  } else {
    columns = parsed.data[0].map((h, i) => String(h || '').trim() || `col${i + 1}`);
  }
  colAliases = columns.map((_, i) => `c${i}`);

  const dataRows = genericHeaders ? parsed.data : parsed.data.slice(1);
  db.run(`CREATE TABLE data (${colAliases.join(', ')})`);

  const padded = new Array(colAliases.length);
  const stmt = db.prepare(`INSERT INTO data VALUES (${colAliases.map(() => '?').join(', ')})`);
  for (const row of dataRows) {
    for (let i = 0; i < padded.length; i++) padded[i] = row[i] ?? null;
    stmt.run(padded);
  }
  stmt.free();

  db.run(`CREATE VIRTUAL TABLE data_fts USING fts4(rowid_ref, content)`);
  db.run(`INSERT INTO data_fts SELECT rowid, ${colAliases.map(a => `COALESCE(${a}, '')`).join(` || ' ' || `)} FROM data`);

  const total = db.exec('SELECT COUNT(*) FROM data')[0].values[0][0];
  self.postMessage({ type: 'ready', columns, total, delimiter: parsed.meta.delimiter });
}

function sanitizeSearch(search) {
  return search.replace(/[-+()\"*\[\]^]/g, ' ').trim();
}

function query({ search, filters, sortCol, sortDir, page, pageSize }) {
  const whereClauses = [];
  const params = [];

  if (search) {
    const safe = sanitizeSearch(search);
    if (safe) {
      whereClauses.push(`rowid IN (SELECT rowid_ref FROM data_fts WHERE content MATCH ?)`);
      params.push(safe + '*');
    }
  }

  for (const [displayCol, { op, val }] of Object.entries(filters)) {
    if (!val) continue;
    const idx = columns.indexOf(displayCol);
    if (idx === -1) continue;
    const alias = colAliases[idx];
    if (op === 'equals') {
      whereClauses.push(`${alias} = ?`);
      params.push(val);
    } else if (op === 'starts') {
      whereClauses.push(`${alias} LIKE ?`);
      params.push(`${val}%`);
    } else if (op === 'ends') {
      whereClauses.push(`${alias} LIKE ?`);
      params.push(`%${val}`);
    } else if (op === 'not_contains') {
      whereClauses.push(`${alias} NOT LIKE ?`);
      params.push(`%${val}%`);
    } else if (op === 'lt') {
      whereClauses.push(`${alias} < ?`);
      params.push(parseFloat(val) || 0);
    } else if (op === 'gt') {
      whereClauses.push(`${alias} > ?`);
      params.push(parseFloat(val) || 0);
    } else {
      whereClauses.push(`${alias} LIKE ?`);
      params.push(`%${val}%`);
    }
  }

  const where = whereClauses.length ? `WHERE ${whereClauses.join(' AND ')}` : '';
  const orderAlias = sortCol ? colAliases[columns.indexOf(sortCol)] : null;
  const order = orderAlias ? `ORDER BY ${orderAlias} ${sortDir}` : '';
  const offset = (page - 1) * pageSize;

  const result = db.exec(
    `SELECT COUNT(*) OVER() AS total, * FROM data ${where} ${order} LIMIT ? OFFSET ?`,
    [...params, pageSize, offset]
  );

  const resultRows = result.length ? result[0].values : [];
  const total = resultRows.length ? resultRows[0][0] : 0;
  const rows = resultRows.map(r => r.slice(1));

  self.postMessage({ type: 'results', rows, total });
}

self.onmessage = async (event) => {
  const { type } = event.data;
  if (type === 'init') {
    const { csvUrl, skiprows, genericHeaders, separator } = event.data;
    try {
      await init(csvUrl, skiprows, genericHeaders, separator);
    } catch (e) {
      self.postMessage({ type: 'error', message: e.message });
    }
  } else if (type === 'updateSettings') {
    const { skiprows, genericHeaders, separator } = event.data;
    try {
      currentSettings = { ...currentSettings, skiprows, genericHeaders, separator };
      await processCSV();
    } catch (e) {
      self.postMessage({ type: 'error', message: e.message });
    }
  } else if (type === 'query') {
    query(event.data);
  }
};
