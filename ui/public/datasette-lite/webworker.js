importScripts("https://cdn.jsdelivr.net/pyodide/v0.27.2/full/pyodide.js");

function log(line) {
  console.log({line})
  self.postMessage({type: 'log', line: line});
}

async function startDatasette(settings) {
  // Using pinned Datasette version for stability
  
  // Check if CSV URLs are provided
  if (!settings.csvUrls || settings.csvUrls.length === 0) {
    self.postMessage({error: 'No CSV file provided. Please add a CSV URL using ?csv=URL parameter.'});
    return;
  }
  
  self.pyodide = await loadPyodide({
    indexURL: "https://cdn.jsdelivr.net/pyodide/v0.27.2/full/",
    fullStdLib: true
  });
  await pyodide.loadPackage('micropip', {messageCallback: log});
  try {
    await self.pyodide.runPythonAsync(`
# https://github.com/pyodide/pyodide/issues/3880#issuecomment-1560130092
import os, sys
import csv
os.link = os.symlink

# Increase CSV field size limit to maximim possible
# https://stackoverflow.com/a/15063941
field_size_limit = sys.maxsize

while True:
    try:
        csv.field_size_limit(field_size_limit)
        break
    except OverflowError:
        field_size_limit = int(field_size_limit / 10)

import sqlite3
from pyodide.http import pyfetch
# Create main database
sqlite3.connect("main.db").execute("vacuum")
names = ["main.db"]

import micropip
# Pin known working versions for stability
await micropip.install("datasette==1.0a14")
await micropip.install("sqlite-utils==3.39")

# Import single CSV file
csv_urls = ${JSON.stringify(settings.csvUrls || [])}
if csv_urls:
    # Process single CSV file with pinned sqlite-utils
    import sqlite_utils, csv as csv_module
    from sqlite_utils.utils import TypeTracker
    from io import StringIO
    
    db = sqlite_utils.Database("main.db")

    # Process single CSV file
    url = csv_urls[0]
    tracker = TypeTracker()
    response = await pyfetch(url)
    csv_bytes = await response.bytes()
    
    skiprows = int(${JSON.stringify(settings.skiprows || 0)})
    generic_headers = skiprows == -1

    csv_lines = csv_bytes.decode('utf-8', errors='ignore').splitlines()
    if not generic_headers and skiprows > 0:
        csv_lines = csv_lines[skiprows:]

    csv_content = '\\n'.join(csv_lines)

    # Auto-detect delimiter
    sample = '\\n'.join(csv_lines[:5])
    semicolon_count = sample.count(';')
    comma_count = sample.count(',')
    delimiter = ';' if semicolon_count > comma_count and semicolon_count > 0 else ','

    # Parse CSV
    csv_reader = csv_module.reader(StringIO(csv_content), delimiter=delimiter)
    rows = list(csv_reader)

    if rows:
        if generic_headers:
            headers = [f"col{i+1}" for i in range(len(rows[0]))]
            data_rows = rows
        else:
            headers = [h.lower() for h in rows[0]]
            seen = {}
            for i, header in enumerate(headers):
                if header in seen:
                    seen[header] += 1
                    headers[i] = f"{header}_{seen[header]}"
                else:
                    seen[header] = 1
            data_rows = rows[1:]
        dict_rows = [dict(zip(headers, row)) for row in data_rows]
        
        db["table"].insert_all(tracker.wrap(dict_rows), alter=True)
        db["table"].transform(types=tracker.types)

        columns = [col.name for col in db["table"].columns if col.type in ('TEXT', 'VARCHAR', 'CHAR')]
        if columns:
            db["table"].enable_fts(columns)
from datasette.app import Datasette
metadata = {
    "about": "CSV Viewer",
    "about_url": "https://github.com/simonw/datasette-lite"
}
ds = Datasette(names, settings={
    "num_sql_threads": 0,
    "suggest_facets": 0,
}, metadata=metadata)
await ds.invoke_startup()
    `);
    datasetteLiteReady();
    self.postMessage({type: 'ready'});
  } catch (error) {
    self.postMessage({error: error.message});
  }
}

// Outside promise pattern
// https://github.com/simonw/datasette-lite/issues/25#issuecomment-1116948381
let datasetteLiteReady;
let readyPromise = new Promise(function(resolve) {
  datasetteLiteReady = resolve;
});

self.onmessage = async (event) => {
  console.log({event, data: event.data});
  if (event.data.type == 'startup') {
    await startDatasette(event.data);
    return;
  }
  // make sure loading is done
  await readyPromise;
  console.log(event, event.data);
  try {
    let [status, contentType, text] = await self.pyodide.runPythonAsync(
      `
      import json
      response = await ds.client.get(
          ${JSON.stringify(event.data.path)},
          follow_redirects=True
      )
      [response.status_code, response.headers.get("content-type"), response.text]
      `
    );
    self.postMessage({status, contentType, text});
  } catch (error) {
    self.postMessage({error: error.message});
  }
};
