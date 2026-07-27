import queryString from 'query-string';

export default function getCanonicalLink(canonicalId, hashQuery) {
  const fragment = queryString.stringify(hashQuery || {});
  return `/profiles/${canonicalId}#${fragment}`;
}
