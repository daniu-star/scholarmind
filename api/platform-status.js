'use strict';

const DEFAULT_BACKEND_ORIGIN = 'https://scholarmind-production-e56b.up.railway.app';

module.exports = async (req, res) => {
  res.setHeader('Cache-Control', 'no-store');

  if (req.method !== 'GET') {
    return res.status(405).json({ status: 'error', error: 'Method not allowed' });
  }

  const backendOrigin = (process.env.BACKEND_ORIGIN || DEFAULT_BACKEND_ORIGIN).replace(/\/+$/, '');
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);

  try {
    const response = await fetch(`${backendOrigin}/api/v1/readyz`, {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    });
    const body = await response.json().catch(() => ({}));
    const ready = response.ok && body.status === 'ok' && body.database?.connected === true;

    return res.status(ready ? 200 : 503).json({
      status: ready ? 'ok' : 'degraded',
      frontend: 'ok',
      backend: response.ok ? body.status || 'unknown' : 'unavailable',
      database: Boolean(body.database?.connected),
    });
  } catch (error) {
    return res.status(503).json({
      status: 'degraded',
      frontend: 'ok',
      backend: 'unavailable',
      database: false,
    });
  } finally {
    clearTimeout(timeout);
  }
};
