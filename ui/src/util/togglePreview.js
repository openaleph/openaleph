import queryString from 'query-string';

export default function togglePreview(navigate, location, entity, profile) {
  const parsedHash = queryString.parse(location.hash);
  const parsedSearch = queryString.parse(location.search);

  parsedHash['preview:mode'] = undefined;

  if (entity) {
    const isOpening = parsedHash['preview:id'] !== entity.id;
    parsedHash['preview:id'] = isOpening ? entity.id : undefined;
    parsedHash['preview:profile'] = profile;

    // If opening a Document from search results, copy the search term into the hash as #q=...
    const isDocument = entity.schema.name === 'Pages'
    if (isOpening && isDocument) {
      const searchTerm = parsedSearch.q || parsedSearch.csq;
      parsedHash.q = searchTerm || undefined;
    }
    // If closing, remove q from hash to avoid stale terms lingering
    if (!isOpening) {
      parsedHash.q = undefined;
    }
  } else {
    parsedHash['preview:id'] = undefined;
    parsedHash['preview:profile'] = undefined;
    parsedHash.page = undefined;
    parsedHash.q = undefined;
  }

  navigate({
    pathname: location.pathname,
    search: location.search,
    hash: queryString.stringify(parsedHash),
  });
}
