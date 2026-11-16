import { endpoint } from 'src/app/api';
import Query from 'app/Query';
import asyncActionCreator from './asyncActionCreator';

export const fetchExports = asyncActionCreator(
  () => async () => {
    const params = { limit: Query.MAX_LIMIT };
    const response = await endpoint.get('exports', { params });
    return { exports: response.data };
  },
  { name: 'FETCH_EXPORTS' }
);

export const triggerQueryExport = asyncActionCreator(
  (exportLink, exportTypes) => async () => {
    const response = await endpoint.post(
      exportLink,
      { export_types: exportTypes },
      {}
    );
    return { data: response.data };
  },
  { name: 'TRIGGER_QUERY_EXPORT' }
);

export const deleteExport = asyncActionCreator(
  (exportId) => async () => {
    await endpoint.delete(`exports/${exportId}`);
    return { exportId };
  },
  { name: 'DELETE_EXPORT' }
);
