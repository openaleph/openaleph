import React, { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Tag } from '@blueprintjs/core';
import { endpoint } from 'app/api';

interface EntitySearchDiscoveryProps {
  result: {
    query_q?: string;
    filters?: Record<string, string[]>;
  };
}

interface SignificantTerm {
  id: string;
  label: string;
  score?: number;
  count?: number;
}

interface DiscoveryResult {
  results?: SignificantTerm[];
  total?: number;
  loading: boolean;
  error?: string;
}

const EntitySearchDiscovery: React.FC<EntitySearchDiscoveryProps> = ({
  result,
}) => {
  const navigate = useNavigate();
  const location = useLocation();

  const [discoveryResult, setDiscoveryResult] = useState<DiscoveryResult>({
    loading: false,
  });

  const parseSearchQuery = (query: string): string[] => {
    const phrases: string[] = [];
    let current = '';
    let inQuotes = false;
    let i = 0;

    while (i < query.length) {
      const char = query[i];

      if (char === '"') {
        inQuotes = !inQuotes;
        current += char;
      } else if (char === ' ' && !inQuotes) {
        if (current.trim()) {
          phrases.push(current.trim());
          current = '';
        }
      } else {
        current += char;
      }
      i++;
    }

    if (current.trim()) {
      phrases.push(current.trim());
    }

    return phrases;
  };

  const removePhrase = (phraseToRemove: string) => {
    const currentQuery = result.query_q || '';
    const phrases = parseSearchQuery(currentQuery);
    const filteredPhrases = phrases.filter(
      (phrase) => phrase !== phraseToRemove
    );
    const newQueryText = filteredPhrases.join(' ');

    // Update the URL with the new query
    const searchParams = new URLSearchParams(location.search);

    // Check which query parameter exists - csq takes precedence over q
    const queryParam = searchParams.has('csq') ? 'csq' : 'q';
    const isCollectionSearch = queryParam === 'csq';

    if (newQueryText.trim()) {
      searchParams.set(queryParam, newQueryText);
    } else {
      searchParams.delete(queryParam);
    }

    navigate({
      pathname: location.pathname,
      search: searchParams.toString(),
      hash: isCollectionSearch ? 'mode=search' : location.hash,
    });
  };

  const handleTermClick = (termLabel: string) => {
    const currentQuery = result.query_q || '';
    const quotedTerm = `"${termLabel}"`;
    const newQueryText = currentQuery
      ? `${currentQuery} ${quotedTerm}`
      : quotedTerm;

    // Update the URL with the new query
    const searchParams = new URLSearchParams(location.search);

    // Check which query parameter exists - csq takes precedence over q
    const queryParam = searchParams.has('csq') ? 'csq' : 'q';
    const isCollectionSearch = queryParam === 'csq';
    searchParams.set(queryParam, newQueryText);

    navigate({
      pathname: location.pathname,
      search: searchParams.toString(),
      hash: isCollectionSearch ? 'mode=search' : location.hash,
    });
  };

  useEffect(() => {
    const fetchDiscoveryData = async () => {
      if (!result.query_q?.trim() && !result.filters?.names?.length) {
        setDiscoveryResult({ loading: false });
        return;
      }

      setDiscoveryResult({ loading: true });

      try {
        const params: Record<string, any> = {
          q: result.query_q,
          limit: 5,
          facet_significant: 'names',
        };

        // Add collection_id filter if it exists in the result filters
        if (result.filters?.collection_id?.length) {
          params['filter:collection_id'] = result.filters.collection_id;
        }

        // Add names filter if it exists in the result filters
        if (result.filters?.names?.length) {
          params['filter:names'] = result.filters.names;
        }

        const response = await endpoint.get('entities', {
          params,
        });

        const significantTerms =
          response.data.facets?.['names.significant_terms']?.values || [];

        setDiscoveryResult({
          loading: false,
          results: significantTerms,
          total: significantTerms.length,
        });
      } catch (error) {
        setDiscoveryResult({
          loading: false,
          error: 'Failed to load discovery results',
        });
      }
    };

    fetchDiscoveryData();
  }, [result.query_q, result.filters?.names, result.filters?.collection_id]);

  if (!result.query_q?.trim() && !result.filters?.names?.length) {
    return null;
  }

  const queryPhrases = result.query_q ? parseSearchQuery(result.query_q) : [];

  // Filter out significant terms that already exist in the query
  const filteredSignificantTerms =
    discoveryResult.results?.filter((term) => {
      const termLabel = term.label.toLowerCase();
      const quotedTerm = `"${termLabel}"`;

      // Check if the term exists in any of the query phrases (case-insensitive)
      const existsInQuery = queryPhrases.some((phrase) => {
        const lowerPhrase = phrase.toLowerCase();
        return (
          lowerPhrase === termLabel ||
          lowerPhrase === quotedTerm ||
          lowerPhrase.includes(termLabel)
        );
      });

      return !existsInQuery;
    }) || [];

  return (
    <div className="EntitySearchDiscovery">
      {queryPhrases.length > 0 && (
        <div style={{ marginBottom: '10px' }}>
          <span>Search terms: </span>
          {queryPhrases.map((phrase, index) => (
            <Tag
              key={index}
              intent="primary"
              onRemove={() => removePhrase(phrase)}
              style={{ marginRight: '5px' }}
            >
              {phrase}
            </Tag>
          ))}
        </div>
      )}
      {discoveryResult.loading && <p>Loading discovery results...</p>}
      {discoveryResult.error && <p>Error: {discoveryResult.error}</p>}
      {filteredSignificantTerms && filteredSignificantTerms.length > 0 && (
        <div>
          <p>
            Your search query is often mentioned with these related terms:{' '}
            {filteredSignificantTerms.map((term, index) => (
              <span key={term.id || index}>
                <button
                  onClick={() => handleTermClick(term.label)}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: '#137cbd',
                    cursor: 'pointer',
                    textDecoration: 'underline',
                    padding: 0,
                    margin: 0,
                    font: 'inherit',
                  }}
                >
                  {term.label}
                </button>
                {index < filteredSignificantTerms.length - 1 && ', '}
              </span>
            ))}
          </p>
        </div>
      )}
    </div>
  );
};

export default EntitySearchDiscovery;
