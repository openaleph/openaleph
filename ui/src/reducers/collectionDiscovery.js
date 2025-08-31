import { createReducer } from 'redux-act';

import { fetchCollectionDiscovery } from 'actions';
import {
  objectLoadStart,
  objectLoadError,
  objectLoadComplete,
} from 'reducers/util';

const initialState = {};

export default createReducer(
  {
    [fetchCollectionDiscovery.START]: (state, { id }) =>
      objectLoadStart(state, id),

    [fetchCollectionDiscovery.ERROR]: (state, { error, args: { id } }) =>
      objectLoadError(state, id, error),

    [fetchCollectionDiscovery.COMPLETE]: (state, { id, data }) => {
      return objectLoadComplete(state, id, data);
    },
  },
  initialState
);
