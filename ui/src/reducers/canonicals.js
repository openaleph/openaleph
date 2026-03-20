import { createReducer } from 'redux-act';

import { fetchCanonical } from 'actions';
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
  },
  initialState
);
