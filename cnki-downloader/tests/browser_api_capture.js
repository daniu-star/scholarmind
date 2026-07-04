/**
 * CNKI API Endpoint Capture Script
 *
 * INSTRUCTIONS:
 * 1. Open Chrome/Edge and go to https://kns.cnki.net/kns8s/
 * 2. Press F12 to open DevTools
 * 3. Go to the "Console" tab
 * 4. Paste this entire script and press Enter
 * 5. Then search for "国际新闻界" in the CNKI search box
 * 6. Click on a paper result to view details
 * 7. Click the download button if available
 * 8. After all interactions, the script will display captured API endpoints
 * 9. Run `copy(capturedAPIs)` to copy results to clipboard
 */

(function() {
    console.log('%c[CNKI API Capture] %cMonitoring network requests...', 'color: green; font-weight: bold', '');

    // Store captured API calls
    window.capturedAPIs = {
        search: [],
        detail: [],
        download: [],
        journal: [],
        other: [],
        raw: []
    };

    // Override XMLHttpRequest
    const origXHROpen = XMLHttpRequest.prototype.open;
    const origXHRSend = XMLHttpRequest.prototype.send;

    XMLHttpRequest.prototype.open = function(method, url) {
        this._capture = { method, url };
        return origXHROpen.apply(this, arguments);
    };

    XMLHttpRequest.prototype.send = function(body) {
        this._capture.body = body;
        this.addEventListener('load', function() {
            const ct = this.getResponseHeader('Content-Type') || '';
            const resp = this.responseText ? this.responseText.slice(0, 500) : '';
            const entry = {
                method: this._capture.method,
                url: this._capture.url,
                body: this._capture.body,
                status: this.status,
                contentType: ct,
                responsePreview: resp
            };

            window.capturedAPIs.raw.push(entry);

            // Categorize
            const url = this._capture.url.toLowerCase();
            if (url.includes('search') || url.includes('brief') || url.includes('result')) {
                window.capturedAPIs.search.push(entry);
            } else if (url.includes('detail') || url.includes('abstract') || url.includes('article')) {
                window.capturedAPIs.detail.push(entry);
            } else if (url.includes('download') || url.includes('.pdf') || url.includes('.caj')) {
                window.capturedAPIs.download.push(entry);
            } else if (url.includes('navi') || url.includes('journal') || url.includes('issue')) {
                window.capturedAPIs.journal.push(entry);
            } else if (ct.includes('json') || resp.startsWith('{') || resp.startsWith('[')) {
                window.capturedAPIs.other.push(entry);
            }

            if (ct.includes('json')) {
                console.log('%c[JSON API]', 'color: orange; font-weight: bold',
                    this._capture.method, url);
            }
        });
        return origXHRSend.apply(this, arguments);
    };

    // Override fetch
    const origFetch = window.fetch;
    window.fetch = function(url, options) {
        const start = Date.now();
        return origFetch.apply(this, arguments).then(async response => {
            const clone = response.clone();
            const ct = clone.headers.get('Content-Type') || '';
            let respPreview = '';

            if (ct.includes('json')) {
                try {
                    const json = await clone.json();
                    respPreview = JSON.stringify(json).slice(0, 500);
                } catch(e) {}
            }

            const entry = {
                method: (options || {}).method || 'GET',
                url: typeof url === 'string' ? url : url.url,
                body: (options || {}).body,
                status: response.status,
                contentType: ct,
                responsePreview: respPreview
            };

            window.capturedAPIs.raw.push(entry);

            const urlStr = entry.url.toLowerCase();
            if (urlStr.includes('search') || urlStr.includes('brief') || urlStr.includes('result')) {
                window.capturedAPIs.search.push(entry);
            } else if (urlStr.includes('detail') || urlStr.includes('abstract') || urlStr.includes('article')) {
                window.capturedAPIs.detail.push(entry);
            } else if (urlStr.includes('download') || urlStr.includes('.pdf') || urlStr.includes('.caj')) {
                window.capturedAPIs.download.push(entry);
            } else if (urlStr.includes('navi') || urlStr.includes('journal') || urlStr.includes('issue')) {
                window.capturedAPIs.journal.push(entry);
            } else if (ct.includes('json')) {
                window.capturedAPIs.other.push(entry);
            }

            if (ct.includes('json')) {
                console.log('%c[FETCH JSON]', 'color: blue; font-weight: bold',
                    (options || {}).method || 'GET', url, respPreview.slice(0, 100));
            }

            return response;
        });
    };

    console.log('%c[CNKI API Capture] %cMonitoring active. Interact with CNKI now!', 'color: green; font-weight: bold', '');
    console.log('%c  1. Search for a journal', 'color: yellow');
    console.log('%c  2. Click on paper results', 'color: yellow');
    console.log('%c  3. Click download button', 'color: yellow');
    console.log('%c  Then run: showResults()', 'color: cyan');

    window.showResults = function() {
        const cats = ['journal', 'search', 'detail', 'download', 'other'];
        for (const cat of cats) {
            if (window.capturedAPIs[cat].length > 0) {
                console.log(`%c=== ${cat.toUpperCase()} (${window.capturedAPIs[cat].length}) ===`, 'font-weight: bold; font-size: 14px');
                for (const entry of window.capturedAPIs[cat]) {
                    console.log(`  ${entry.method} ${entry.url}`);
                    if (entry.body) console.log(`    Body: ${entry.body.slice(0, 200)}`);
                    if (entry.responsePreview) console.log(`    Response: ${entry.responsePreview.slice(0, 200)}`);
                }
            }
        }
        console.log('%cTo copy results: copy(JSON.stringify(window.capturedAPIs, null, 2))', 'color: cyan');
    };

})();
