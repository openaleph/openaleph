import queryString from 'query-string';
import { getGroupField } from 'components/SearchField/util';

const DEFAULT_COLUMNS = ['countries', 'dates'];

// Use arrayFormat: 'comma' for consistent comma-separated array handling
const QUERY_STRING_OPTIONS = { arrayFormat: 'comma' };

export function getColumnsFromHash(location) {
  const parsedHash = queryString.parse(location.hash, QUERY_STRING_OPTIONS);
  let columnsParam = parsedHash.columns;

  if (!columnsParam) return null;

  // Ensure columnsParam is always an array
  const names = Array.isArray(columnsParam) ? columnsParam : [columnsParam];

  return names.filter(Boolean).map((name) => {
    const groupField = getGroupField(name);
    if (groupField) return groupField;
    return { name, isProperty: true };
  });
}

export function setColumnsInHash(navigate, location, columns) {
  const parsedHash = queryString.parse(location.hash, QUERY_STRING_OPTIONS);

  if (!columns || columns.length === 0) {
    delete parsedHash.columns;
  } else {
    parsedHash.columns = columns.map((c) => c.name);
  }

  navigate(
    {
      pathname: location.pathname,
      search: location.search,
      hash: queryString.stringify(parsedHash, QUERY_STRING_OPTIONS),
    },
    { replace: true }
  );
}

export function getDefaultColumns() {
  return DEFAULT_COLUMNS.map(getGroupField);
}
