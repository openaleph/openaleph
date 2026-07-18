import { createReducer } from 'redux-act';

import timestamp from 'util/timestamp';

import {
  forceMutate,
  createCollection,
  updateCollection,
  deleteCollection,
  createEntityMapping,
  updateEntityMapping,
  deleteEntityMapping,
  triggerCollectionCancel,
  updateCollectionPermissions,
  createEntity,
  createEntitySetMutate,
  updateEntitySetItemMutate,
  deleteEntity,
  deleteEntitySet,
  updateRole,
  deleteAlert,
  createAlert,
  createBookmark,
  deleteBookmark,
  pairwiseJudgement,
  loginWithToken,
  logout,
} from 'actions';

const initialState = {
  global: timestamp(),
};

function update(state, key = 'global') {
  return {
    ...state,
    [key]: timestamp(),
  };
}

export default createReducer(
  {
    [forceMutate]: (state) => update(state),
    [loginWithToken]: (state) => update(state),
    [logout]: (state) => update(state),
    // Clear out the redux cache when operations are performed that
    // may affect the content of the results.
    [createCollection.COMPLETE]: (state) => update(state),
    [updateCollection.COMPLETE]: (state) => update(state),
    [deleteCollection.COMPLETE]: (state) => update(state),
    [createEntityMapping.COMPLETE]: (state) => update(state),
    [updateEntityMapping.COMPLETE]: (state) => update(state),
    [deleteEntityMapping.COMPLETE]: (state) => update(state),
    [triggerCollectionCancel.COMPLETE]: (state) => update(state),
    [updateCollectionPermissions.COMPLETE]: (state) => update(state),
    [createEntity.COMPLETE]: (state) => update(state),
    [createEntitySetMutate.COMPLETE]: (state) => update(state),
    [updateEntitySetItemMutate.COMPLETE]: (state) => update(state),
    [pairwiseJudgement.COMPLETE]: (state) => update(state),
    [deleteEntity.COMPLETE]: (state) => update(state),
    [deleteEntitySet.COMPLETE]: (state) => update(state),
    [updateRole.COMPLETE]: (state) => update(state),
    [createAlert.COMPLETE]: (state) => update(state),
    [deleteAlert.COMPLETE]: (state) => update(state),
    [createBookmark.COMPLETE]: (state) => update(state, 'bookmarks'),
    [deleteBookmark.COMPLETE]: (state) => update(state, 'bookmarks'),
  },
  initialState
);
