/**
 * CNKI Complete API Capture — Run this in DevTools Console
 *
 * INSTRUCTIONS:
 * 1. Open Chrome → go to https://kns.cnki.net/kns8s/
 * 2. F12 → Console → Paste this entire script → Enter
 * 3. Search for "国际新闻界" in the search box and wait for results
 * 4. Click on the first paper result, wait for detail page
 * 5. Click the download button (PDF or CAJ)
 * 6. Run: copy(JSON.stringify(window.__cnkiAPIs, null, 2))
 * 7. Paste the JSON into a file: sessions/cnki_api_capture.json
 *
 * This will capture the EXACT request format needed for Python replication.
 */

(function() {
    'use strict';

    window.__cnkiAPIs = {
        capturedAt: new Date().toISOString(),
        cookies: document.cookie,
        userAgent: navigator.userAgent,
        apis: []
    };

    // ── Intercept XMLHttpRequest ──
    const OrigXHR = window.XMLHttpRequest;
    window.XMLHttpRequest = function() {
        const xhr = new OrigXHR();
        const origOpen = xhr.open;
        const origSend = xhr.send;
        const origSetRequestHeader = xhr.setRequestHeader;
        const requestHeaders = {};

        xhr.open = function(method, url) {
            this._method = method;
            this._url = url;
            return origOpen.apply(this, arguments);
        };

        xhr.setRequestHeader = function(name, value) {
            requestHeaders[name] = value;
            return origSetRequestHeader.apply(this, arguments);
        };

        xhr.send = function(body) {
            const start = Date.now();
            this.addEventListener('load', function() {
                const ct = this.getResponseHeader('Content-Type') || '';
                // Only capture JSON API calls (the data endpoints)
                if (ct.includes('json') || ct.includes('javascript') ||
                    this.responseText.trim().startsWith('{') ||
                    this.responseText.trim().startsWith('[')) {

                    let responseBody = this.responseText;
                    try {
                        const json = JSON.parse(this.responseText);
                        responseBody = JSON.stringify(json); // normalize
                    } catch(e) {}

                    const entry = {
                        type: 'XHR',
                        method: this._method,
                        url: this._url,
                        status: this.status,
                        contentType: ct,
                        requestHeaders: {...requestHeaders},
                        requestBody: body,
                        responseBody: responseBody.slice(0, 5000), // limit size
                        responseSize: this.responseText.length,
                        duration: Date.now() - start
                    };

                    window.__cnkiAPIs.apis.push(entry);

                    console.log('%c[API CAPTURED]', 'background:green;color:white;padding:2px 6px',
                        this._method, this._url.split('?')[0].split('/').slice(-2).join('/'),
                        `(${this.responseText.length} bytes, ${Date.now()-start}ms)`);
                }
            });
            return origSend.apply(this, arguments);
        };
    };

    // ── Intercept fetch ──
    const origFetch = window.fetch;
    window.fetch = async function(url, options = {}) {
        const start = Date.now();
        const method = options.method || 'GET';
        const body = options.body;
        const headers = options.headers || {};

        const response = await origFetch.apply(this, arguments);
        const clone = response.clone();
        const ct = clone.headers.get('Content-Type') || '';

        if (ct.includes('json') || ct.includes('javascript')) {
            try {
                const json = await clone.json();
                const entry = {
                    type: 'FETCH',
                    method: method,
                    url: typeof url === 'string' ? url : url.url,
                    status: response.status,
                    contentType: ct,
                    requestHeaders: typeof headers === 'object' && !(headers instanceof Headers) ?
                        headers : Object.fromEntries(new Headers(headers).entries()),
                    requestBody: body,
                    responseBody: JSON.stringify(json).slice(0, 5000),
                    responseSize: JSON.stringify(json).length,
                    duration: Date.now() - start
                };

                window.__cnkiAPIs.apis.push(entry);

                console.log('%c[FETCH CAPTURED]', 'background:blue;color:white;padding:2px 6px',
                    method, typeof url === 'string' ? url.split('?')[0].split('/').slice(-2).join('/') : url.url.split('?')[0].split('/').slice(-2).join('/'),
                    `(${JSON.stringify(json).length} bytes, ${Date.now()-start}ms)`);
            } catch(e) {}
        }

        return response;
    };

    console.log('%c✅ CNKI API Capture Active!', 'font-size:16px;color:green;font-weight:bold');
    console.log('%c  1. Search for a journal paper on CNKI', 'font-size:13px');
    console.log('%c  2. Click a paper result to view details', 'font-size:13px');
    console.log('%c  3. Click the download (PDF/CAJ) button', 'font-size:13px');
    console.log('%c  4. Run: copy(JSON.stringify(window.__cnkiAPIs, null, 2))', 'font-size:13px;color:yellow;font-weight:bold');
    console.log('%c     Then paste into: cnki-downloader/sessions/cnki_api_capture.json', 'font-size:13px');
})();
