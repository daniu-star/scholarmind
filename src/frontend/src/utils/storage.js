export const storage = {
  get(key, defaultValue = null) {
    try {
      const val = localStorage.getItem(key);
      return val ? JSON.parse(val) : defaultValue;
    } catch { return defaultValue; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch {}
  },
  remove(key) { localStorage.removeItem(key); },
  clear() { localStorage.clear(); }
};