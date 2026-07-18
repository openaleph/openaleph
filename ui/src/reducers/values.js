import { createReducer } from 'redux-act';

import { fetchEntityTags, fetchCanonicalTags } from 'actions';

const initialState = {};

function updateState(state, { data }) {
  const values = {};
  if (!data?.results?.length) {
    return state;
  }
  data.results.forEach((res) => {
    values[`${res.field}:${res.value}`] = res.count;
  });
  return { ...values, ...state };
}

export default createReducer(
  {
    [fetchEntityTags.COMPLETE]: updateState,
    [fetchCanonicalTags.COMPLETE]: updateState,
  },
  initialState
);
