import { createReducer } from 'redux-act';

import {
  queryRoles,
  fetchRole,
  updateRole,
  createCollection,
  deleteCollection,
} from 'actions';
import {
  resultObjects,
  objectLoadStart,
  objectLoadError,
  objectLoadComplete,
} from './util';

const initialState = {};

// The investigation quota is served on the current user's role only, so
// after a collection is created or deleted that role is marked stale and
// re-fetched by AuthButtons.
function invalidateQuota(state) {
  const next = { ...state };
  Object.keys(next).forEach((id) => {
    if (next[id]?.investigations_count !== undefined) {
      next[id] = { ...next[id], shouldLoadDeep: true };
    }
  });
  return next;
}

export default createReducer(
  {
    [queryRoles.COMPLETE]: (state, { result }) => resultObjects(state, result),
    [fetchRole.START]: (state, { id }) => objectLoadStart(state, id),
    [fetchRole.ERROR]: (state, { error, args: { id } }) =>
      objectLoadError(state, id, error),
    [fetchRole.COMPLETE]: (state, { id, data }) =>
      objectLoadComplete(state, id, data),
    [updateRole.COMPLETE]: (state, { id, data }) =>
      objectLoadComplete(state, id, data),
    [createCollection.COMPLETE]: (state) => invalidateQuota(state),
    [deleteCollection.COMPLETE]: (state) => invalidateQuota(state),
  },
  initialState
);
