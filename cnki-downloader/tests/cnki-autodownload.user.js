// ==UserScript==
// @name         CNKI Auto PDF Download
// @namespace    http://scholarmind.ai/
// @version      1.0
// @description  Auto-clicks PDF download button on CNKI paper pages
// @author       ScholarMind
// @match        https://kns.cnki.net/kcms2/article/abstract*
// @match        https://kns.cnki.net/kcms/detail/*
// @icon         https://www.cnki.net/favicon.ico
// @grant        none
// @run-at       document-end
// ==/UserScript==

(function() {
    'use strict';

    console.log('[CNKI Auto-Download] Script loaded');

    // Configuration
    const CONFIG = {
        format: 'pdf',           // 'pdf' or 'caj' or 'any'
        delay: 2000,             // ms before clicking
        maxRetries: 20,          // max attempts to find button
        retryInterval: 1500,     // ms between retries
        showIndicator: true,     // show visual indicator
    };

    let attempts = 0;
    let clicked = false;

    function findDownloadButton() {
        if (clicked) return;

        const links = document.querySelectorAll('a');
        let targetBtn = null;

        // Priority 1: Exact "PDF下载" text
        for (const link of links) {
            const text = (link.textContent || '').trim();
            if (CONFIG.format === 'pdf' && text.includes('PDF') && text.includes('下载')) {
                targetBtn = link;
                break;
            }
            if (CONFIG.format === 'caj' && text.includes('CAJ') && text.includes('下载')) {
                targetBtn = link;
                break;
            }
            if (CONFIG.format === 'any' && text.includes('下载') && (text.includes('PDF') || text.includes('CAJ'))) {
                targetBtn = link;
                break;
            }
        }

        // Priority 2: Any "PDF下载" variant
        if (!targetBtn) {
            for (const link of links) {
                const text = (link.textContent || '').trim();
                if (text.includes('PDF')) {
                    targetBtn = link;
                    break;
                }
            }
        }

        // Priority 3: Link containing "download/order" in href
        if (!targetBtn) {
            for (const link of links) {
                const href = (link.href || '').toLowerCase();
                if (href.includes('download/order') || href.includes('download?id=')) {
                    targetBtn = link;
                    break;
                }
            }
        }

        // Priority 4: Any link with "下载" text
        if (!targetBtn) {
            for (const link of links) {
                const text = (link.textContent || '').trim();
                if (text.includes('下载') && text.length < 10) {
                    targetBtn = link;
                    break;
                }
            }
        }

        if (targetBtn) {
            clicked = true;
            const btnText = targetBtn.textContent.trim();
            const btnHref = targetBtn.href;

            console.log('[CNKI Auto-Download] Found button:', btnText);
            console.log('[CNKI Auto-Download] URL:', btnHref.substring(0, 100));

            // Show visual indicator
            if (CONFIG.showIndicator) {
                const indicator = document.createElement('div');
                indicator.style.cssText = [
                    'position: fixed',
                    'top: 0',
                    'left: 0',
                    'right: 0',
                    'background: #1a73e8',
                    'color: white',
                    'padding: 15px 25px',
                    'z-index: 99999',
                    'text-align: center',
                    'font-size: 16px',
                    'font-weight: bold',
                    'box-shadow: 0 2px 10px rgba(0,0,0,0.3)',
                    'pointer-events: none',
                ].join(';');
                indicator.textContent = 'Auto-downloading PDF... Please wait';
                document.body.appendChild(indicator);

                setTimeout(() => {
                    indicator.textContent = 'Download started! This tab will close in 8 seconds...';
                    setTimeout(() => {
                        window.close();
                    }, 8000);
                }, 2000);
            }

            // Highlight the button
            targetBtn.style.outline = '4px solid #ff0000';
            targetBtn.style.backgroundColor = '#ffeb3b';

            // CLICK IT!
            setTimeout(() => {
                console.log('[CNKI Auto-Download] CLICKING!');
                targetBtn.click();
            }, CONFIG.delay);

        } else {
            attempts++;
            if (attempts < CONFIG.maxRetries) {
                console.log('[CNKI Auto-Download] Button not found yet, retry ' + attempts + '/' + CONFIG.maxRetries);
                setTimeout(findDownloadButton, CONFIG.retryInterval);
            } else {
                console.log('[CNKI Auto-Download] No download button found after ' + CONFIG.maxRetries + ' attempts');
                // Auto-close tab since there's nothing to download
                setTimeout(() => window.close(), 3000);
            }
        }
    }

    // Start searching for the download button
    if (document.readyState === 'complete' || document.readyState === 'interactive') {
        setTimeout(findDownloadButton, CONFIG.delay);
    } else {
        window.addEventListener('DOMContentLoaded', () => {
            setTimeout(findDownloadButton, CONFIG.delay);
        });
    }

})();
