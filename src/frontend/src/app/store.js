import { storage } from '../utils/storage.js';

export function createStore(initialState) {
  const listeners = new Map();

  const state = new Proxy({ ...initialState }, {
    set(target, key, value) {
      target[key] = value;
      if (listeners.has(key)) {
        listeners.get(key).forEach(cb => cb(value, key));
      }
      if (listeners.has('*')) {
        listeners.get('*').forEach(cb => cb(value, key));
      }
      return true;
    }
  });

  return {
    state,
    watch(key, callback) {
      if (!listeners.has(key)) listeners.set(key, new Set());
      listeners.get(key).add(callback);
      return () => listeners.get(key)?.delete(callback);
    },
  };
}

export const { state, watch } = createStore({
  currentPage: window.location.hash.slice(1) || 'homepage',
  discipline: storage.get('sm_discipline', null),
  researchType: storage.get('sm_researchType', null),
  readiness: storage.get('sm_readiness', null),
  uploadedFiles: storage.get('sm_uploads', {}),
  currentSessionId: storage.get('sm_sessionId', ''),
  cnkiResults: [],
  skills: [],
  messages: {},
  settings: {
    theme: storage.get('sm_theme', 'dark'),
    apiBase: storage.get('sm_apiBase', 'http://localhost:8000'),
  },
});

// Auto-persist key state to localStorage
watch('discipline', v => storage.set('sm_discipline', v));
watch('researchType', v => storage.set('sm_researchType', v));
watch('readiness', v => storage.set('sm_readiness', v));
watch('settings', v => { storage.set('sm_theme', v?.theme || 'dark'); });