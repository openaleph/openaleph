import { createReducer } from 'redux-act';

import { fetchCanonical, fetchCanonicalStatements } from 'actions';
import {
  objectLoadComplete,
  objectLoadError,
  objectLoadStart,
} from 'reducers/util';

const initialState = {};

export default createReducer(
  {
    [fetchCanonical.START]: (state, { id }) => objectLoadStart(state, id),

    [fetchCanonical.ERROR]: (state, { error, args: { id } }) =>
      objectLoadError(state, id, error),

    [fetchCanonical.COMPLETE]: (state, { id, data }) =>
      objectLoadComplete(state, id, data),

    [fetchCanonicalStatements.START]: (state, { id }) =>
      objectLoadStart(state, `${id}/statements`),

    [fetchCanonicalStatements.ERROR]: (state, { error, args: { id } }) =>
      objectLoadError(state, `${id}/statements`, error),

    [fetchCanonicalStatements.COMPLETE]: (state, { id, data }) =>
      objectLoadComplete(state, `${id}/statements`, data),
  },
  initialState
);
