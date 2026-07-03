import { api } from './api.js';

const BASE = '/api/v1';

export const paperPipelineApi = {
  startPipeline(data) {
    return api.post(`${BASE}/paper-pipeline/start`, data);
  },
  getStatus(pipelineId) {
    return api.get(`${BASE}/paper-pipeline/${pipelineId}/status`);
  },
  getResult(pipelineId) {
    return api.get(`${BASE}/paper-pipeline/${pipelineId}/result`);
  },
  listPipelines(sessionId) {
    const qs = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
    return api.get(`${BASE}/paper-pipeline${qs}`);
  },
};

export const paperReviewApi = {
  startReview(data) {
    return api.post(`${BASE}/paper-review/start`, data);
  },
  getStatus(reviewId) {
    return api.get(`${BASE}/paper-review/${reviewId}/status`);
  },
  getResult(reviewId) {
    return api.get(`${BASE}/paper-review/${reviewId}/result`);
  },
  listReviews(sessionId) {
    const qs = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
    return api.get(`${BASE}/paper-review${qs}`);
  },
};
