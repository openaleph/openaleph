import { endpoint } from 'app/api';
import asyncActionCreator from './asyncActionCreator';
import { queryEndpoint } from './util';

export const queryCanonicalExpand = asyncActionCreator(
  (query) => async () => queryEndpoint(query),
  { name: 'QUERY_CANONICAL_EXPAND' }
);

export const fetchCanonical = asyncActionCreator(
  ({ id }) =>
    async () => {
      const response = await endpoint.get(`canonical/${id}`);
      return { id, data: response.data };
    },
  { name: 'FETCH_CANONICAL' }
);

export const fetchCanonicalTags = asyncActionCreator(
  ({ id }) =>
    async () => {
      const response = await endpoint.get(`canonical/${id}/tags`);
      return { id, data: response.data };
    },
  { name: 'FETCH_CANONICAL_TAGS' }
);

export const fetchCanonicalStatements = asyncActionCreator(
  ({ id }) =>
    async () => {
      const response = await endpoint.get(`canonical/${id}/statements`);
      return { id, data: response.data };
    },
  { name: 'FETCH_CANONICAL_STATEMENTS' }
);

export const pairwiseJudgement = asyncActionCreator(
  ({ entity, match, judgement }) =>
    async () => {
      const data = { entity_id: entity.id, match_id: match.id, judgement };
      const response = await endpoint.post(`xref/_decide`, data);
      return {
        entityId: entity.id,
        canonicalId: response.data.canonical_id,
      };
    },
  { name: 'PAIRWISE_JUDGEMENT' }
);
