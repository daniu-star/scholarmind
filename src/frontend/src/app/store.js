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

// Debounce utility for localStorage writes
function debouncedStore(fn, delay = 300) {
  let timers = {};
  return function(key, value) {
    if (timers[key]) clearTimeout(timers[key]);
    timers[key] = setTimeout(() => {
      fn(key, value);
      delete timers[key];
    }, delay);
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
  auth: {
    user: storage.get('sm_user', null),
    token: storage.get('sm_token', null),
    isAuthenticated: Boolean(storage.get('sm_token', null)),
    entitlements: storage.get('sm_entitlements', null),
  },
});

// Debounced persist — prevents main-thread blocking from sync localStorage I/O
const setDebounced = debouncedStore((key, value) => storage.set(key, value), 300);

// Auto-persist key state to localStorage (debounced)
watch('discipline', v => setDebounced('sm_discipline', v));
watch('researchType', v => setDebounced('sm_researchType', v));
watch('readiness', v => setDebounced('sm_readiness', v));
watch('currentSessionId', v => setDebounced('sm_sessionId', v));
watch('settings', v => { setDebounced('sm_theme', v?.theme || 'dark'); setDebounced('sm_apiBase', v?.apiBase || ''); });
watch('messages', v => setDebounced('sm_messages', v));
watch('cnkiResults', v => setDebounced('sm_cnkiResults', v));
watch('skills', v => setDebounced('sm_skills', v));
watch('auth', v => {
  storage.set('sm_user', v?.user || null);
  storage.set('sm_token', v?.token || null);
  storage.set('sm_entitlements', v?.entitlements || null);
});