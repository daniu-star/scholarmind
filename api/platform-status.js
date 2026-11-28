'use strict';

const DEFAULT_BACKEND_ORIGIN = 'https://views-flexibility-kings-manchester.trycloudflare.com';

module.exports = async (req, res) => {
  res.setHeader('Cache-Control', 'no-store');

  if (req.method !== 'GET') {
    return res.status(405).json({ status: 'error', error: 'Method not allowed' });
  }

  const backendOrigin = (process.env.BACKEND_ORIGIN || DEFAULT_BACKEND_ORIGIN).replace(/\/+$/, '');
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);

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
      backend_code: response.status,
      database: Boolean(body.database?.connected),
      detail: ready
        ? 'All systems operational'
        : response.ok
          ? `Backend OK but database disconnected (pool=${JSON.stringify(body.database?.pool || {})})`
          : `Backend responded with HTTP ${response.status}`,
    });
  } catch (error) {
    const errMsg =
      error.name === 'AbortError'
        ? 'Backend health check timed out after 15s'
        : `Backend unreachable: ${error.message}`;
    return res.status(503).json({
      status: 'degraded',
      frontend: 'ok',
      backend: 'unavailable',
      backend_code: null,
      database: false,
      detail: errMsg,
    });
  } finally {
    clearTimeout(timeout);
  }
};
