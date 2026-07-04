// CNKI Auto PDF Download - Content Script
// Auto-clicks the PDF download button on CNKI paper detail pages

(function() {
    'use strict';

    console.log('[CNKI AutoDL] Content script loaded');

    let attempts = 0;
    const MAX_ATTEMPTS = 25;
    const RETRY_MS = 1500;
    let clicked = false;

    function findAndClick() {
        if (clicked) return;

        attempts++;
        const links = document.querySelectorAll('a');
        let target = null;

        // Priority 1: Exact "PDF下载"
        for (const a of links) {
            const t = (a.textContent || '').trim();
            if (t.includes('PDF') && t.includes('下载')) {
                target = a;
                break;
            }
        }

        // Priority 2: "PDF" text
        if (!target) {
            for (const a of links) {
                const t = (a.textContent || '').trim();
                if (t === 'PDF下载' || t.includes('PDF下载')) {
                    target = a;
                    break;
                }
            }
        }

        // Priority 3: Any PDF link
        if (!target) {
            for (const a of links) {
                if ((a.textContent || '').trim().includes('PDF')) {
                    target = a;
                    break;
                }
            }
        }

        // Priority 4: download/order href
        if (!target) {
            for (const a of links) {
                if ((a.href || '').toLowerCase().includes('download/order')) {
                    target = a;
                    break;
                }
            }
        }

        // Priority 5: Any download link
        if (!target) {
            for (const a of links) {
                const t = (a.textContent || '').trim();
                if (t.includes('下载') && t.length < 8) {
                    target = a;
                    break;
                }
            }
        }

        if (target) {
            clicked = true;
            const text = target.textContent.trim();
            const href = target.href;

            console.log('[CNKI AutoDL] Found:', text);
            console.log('[CNKI AutoDL] URL:', href.substring(0, 100));

            // Visual indicator
            const banner = document.createElement('div');
            banner.id = 'cnki-autodl-banner';
            banner.style.cssText = 'position:fixed;top:0;left:0;right:0;background:#1a73e8;color:white;padding:14px 20px;z-index:2147483647;text-align:center;font-size:15px;font-weight:bold;box-shadow:0 2px 8px rgba(0,0,0,0.3);font-family:"Microsoft YaHei",sans-serif';
            banner.textContent = 'CNKI Auto-Download: Clicking "' + text + '"...';
            document.body.appendChild(banner);

            // Highlight the button
            target.style.outline = '3px solid red';
            target.style.background = '#ffeb3b';
            target.style.color = '#000';

            // Click after short delay
            setTimeout(function() {
                console.log('[CNKI AutoDL] CLICKING!');
                target.click();

                banner.textContent = 'Download started! Tab will close in 12 seconds...';
                setTimeout(function() {
                    banner.textContent = 'Closing tab...';
                    setTimeout(function() { window.close(); }, 1000);
                }, 11000);
            }, 2000);

        } else if (attempts < MAX_ATTEMPTS) {
            console.log('[CNKI AutoDL] Waiting... (' + attempts + '/' + MAX_ATTEMPTS + ')');
            setTimeout(findAndClick, RETRY_MS);
        } else {
            console.log('[CNKI AutoDL] No download button found after ' + MAX_ATTEMPTS + ' attempts');
            // Auto-close tab since nothing to download
            setTimeout(function() { window.close(); }, 2000);
        }
    }

    // Start searching
    if (document.readyState === 'complete' || document.readyState === 'interactive') {
        setTimeout(findAndClick, 2500);
    } else {
        window.addEventListener('DOMContentLoaded', function() {
            setTimeout(findAndClick, 2500);
        });
    }

})();
