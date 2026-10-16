// Opens the report a timeline mark was built from, in a new tab. `endpoint(id)` is the screen's own document url.
import { apiClient } from '../../services/api.client';

export const openDocumentWith = (endpoint, params = {}) => async (id) => {
  try {
    const res = await apiClient.get(endpoint(id), { params });
    const link = (res.data?.data || res.data)?.file_data;
    if (link) window.open(link, '_blank', 'noopener');
  } catch {
    // no preview available: the mark simply does nothing
  }
};
