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
  currentSessionId: storage.get('sm_sessionId', crypto.randomUUID()),
  cnkiResults: storage.get('sm_cnkiResults', []),
  skills: storage.get('sm_skills', []),
  messages: storage.get('sm_messages', {}),
  settings: {
    theme: storage.get('sm_theme', 'dark'),
    apiBase: storage.get('sm_apiBase', ''),
  },
});

// Auto-persist key state to localStorage
watch('discipline', v => storage.set('sm_discipline', v));
watch('researchType', v => storage.set('sm_researchType', v));
watch('readiness', v => storage.set('sm_readiness', v));
watch('currentSessionId', v => storage.set('sm_sessionId', v));
watch('settings', v => { storage.set('sm_theme', v?.theme || 'dark'); storage.set('sm_apiBase', v?.apiBase || ''); });
watch('messages', v => storage.set('sm_messages', v));
watch('cnkiResults', v => storage.set('sm_cnkiResults', v));
watch('skills', v => storage.set('sm_skills', v));