/**
 * CNKI Auto Download Script - Run in Chrome DevTools Console
 *
 * This script runs INSIDE your real browser where CNKI authentication works.
 * It automates the complete download flow for an entire journal.
 *
 * INSTRUCTIONS:
 * 1. Open Chrome and go to https://kns.cnki.net/kns8s/
 * 2. F12 -> Console -> Paste this entire script -> Press Enter
 * 3. The script will automatically:
 *    a. Search for the specified journal
 *    b. Extract all paper links
 *    c. Open each paper and click the "PDF下载" button
 *    d. Download the PDF to your default downloads folder
 *
 * CONFIGURATION: Edit the settings below before running.
 */

const CONFIG = {
    // Journal to download
    journalName: '国际新闻界',
    journalCode: 'GJXW',

    // Year range
    yearStart: 2024,
    yearEnd: 2026,

    // Download format: 'pdf' or 'caj' or 'both'
    downloadFormat: 'pdf',

    // Delay between downloads (milliseconds)
    delayBetweenPapers: 3000,

    // Maximum papers to download (0 = unlimited)
    maxPapers: 0,
};

// ============================================================
// DO NOT EDIT BELOW THIS LINE
// ============================================================

(async function() {
    'use strict';

    let downloadedCount = 0;
    let skippedCount = 0;
    let failedCount = 0;
    const results = [];

    console.log('%c========================================', 'color: cyan; font-size: 16px');
    console.log('%c CNKI Auto Download Script v1.0', 'color: cyan; font-size: 16px');
    console.log('%c========================================', 'color: cyan; font-size: 16px');
    console.log(`Journal: ${CONFIG.journalName}`);
    console.log(`Years: ${CONFIG.yearStart}-${CONFIG.yearEnd}`);
    console.log(`Format: ${CONFIG.downloadFormat}`);
    console.log('');

    /**
     * Step 1: Get paper list from RSS feed
     */
    async function getPaperList() {
        console.log('%c[Step 1] Fetching paper list from RSS...', 'color: yellow; font-weight: bold');

        const papers = [];
        const rssUrl = `https://rss.cnki.net/knavi/rss/${CONFIG.journalCode}?pcode=CJFD,CCJD`;

        try {
            const response = await fetch(rssUrl);
            const xmlText = await response.text();
            const parser = new DOMParser();
            const xmlDoc = parser.parseFromString(xmlText, 'text/xml');
            const items = xmlDoc.querySelectorAll('item');

            items.forEach(item => {
                const title = item.querySelector('title')?.textContent?.trim() || '';
                const link = item.querySelector('link')?.textContent?.trim() || '';
                const author = item.querySelector('author')?.textContent?.trim() || '';
                const pubDate = item.querySelector('pubDate')?.textContent?.trim() || '';

                if (title && link) {
                    papers.push({ title, link, author, pubDate });
                }
            });

            console.log(`  Found ${papers.length} papers`);
            return papers;
        } catch (e) {
            console.error('  RSS fetch failed:', e);
            return [];
        }
    }

    /**
     * Step 2: Open paper detail page and extract download URL
     */
    async function getDownloadUrl(paperUrl) {
        try {
            const response = await fetch(paperUrl);
            const html = await response.text();

            // Extract download order URLs
            const orderMatch = html.match(/bar\.cnki\.net\/bar\/download\/order\?id=([^"'\s&]+)/g);
            if (!orderMatch || orderMatch.length === 0) return null;

            // First match is PDF, second is CAJ (if available)
            const pdfUrl = 'https://' + orderMatch[0];
            const cajUrl = orderMatch.length > 1 ? 'https://' + orderMatch[1] : null;

            if (CONFIG.downloadFormat === 'pdf') return pdfUrl;
            if (CONFIG.downloadFormat === 'caj') return cajUrl || pdfUrl;
            return pdfUrl; // default to PDF
        } catch (e) {
            console.error('  Detail page fetch failed:', e);
            return null;
        }
    }

    /**
     * Step 3: Trigger download in browser
     */
    async function downloadPaper(paperUrl, title) {
        return new Promise((resolve) => {
            console.log(`  Downloading: ${title.substring(0, 60)}...`);

            // Method 1: Open paper detail page in new window, then click download
            const win = window.open(paperUrl, '_blank');
            if (!win) {
                console.log('    Popup blocked! Please allow popups and retry.');
                resolve(false);
                return;
            }

            // Wait for page to load, then find and click download button
            let attempts = 0;
            const checkInterval = setInterval(() => {
                attempts++;
                try {
                    // Try to find PDF download link
                    const links = win.document.querySelectorAll('a');
                    let downloadBtn = null;

                    for (const link of links) {
                        const text = (link.textContent || '').trim();
                        const href = (link.href || '').toLowerCase();

                        if (CONFIG.downloadFormat === 'pdf' && text.includes('PDF')) {
                            downloadBtn = link;
                            break;
                        }
                        if (CONFIG.downloadFormat === 'caj' && text.includes('CAJ')) {
                            downloadBtn = link;
                            break;
                        }
                        if (text.includes('PDF') || text.includes('下载')) {
                            downloadBtn = link;
                            break;
                        }
                    }

                    if (downloadBtn) {
                        clearInterval(checkInterval);
                        console.log(`    Found download button: ${downloadBtn.textContent.trim()}`);
                        downloadBtn.click();

                        // Wait for download to start, then close window
                        setTimeout(() => {
                            try { win.close(); } catch(e) {}
                            resolve(true);
                        }, 5000);
                    }
                } catch (e) {
                    // Cross-origin error - page might have navigated
                }

                if (attempts > 30) { // 15 seconds timeout
                    clearInterval(checkInterval);
                    try { win.close(); } catch(e) {}
                    console.log('    Timeout waiting for download button');
                    resolve(false);
                }
            }, 500);
        });
    }

    /**
     * Alternative: Direct download URL navigation
     */
    async function downloadDirect(downloadUrl, title) {
        console.log(`  Direct download: ${title.substring(0, 60)}...`);

        // Navigate to the download URL - browser will handle the auth chain
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.download = '';
        link.target = '_blank';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);

        // Wait for download to start
        await new Promise(r => setTimeout(r, CONFIG.delayBetweenPapers));
        return true;
    }

    // ============================================================
    // MAIN
    // ============================================================

    console.log('%c[Step 1] Getting paper list...', 'color: yellow; font-weight: bold');
    const papers = await getPaperList();

    if (papers.length === 0) {
        console.error('No papers found! Check journal code and network.');
        return;
    }

    const limit = CONFIG.maxPapers > 0 ? Math.min(CONFIG.maxPapers, papers.length) : papers.length;
    console.log(`\n%c[Step 2] Processing ${limit} papers...`, 'color: yellow; font-weight: bold');

    for (let i = 0; i < limit; i++) {
        const paper = papers[i];
        console.log(`\n%c[${i+1}/${limit}] ${paper.title.substring(0, 60)}`, 'color: white; font-weight: bold');

        // First try: get download URL from detail page
        const downloadUrl = await getDownloadUrl(paper.link);

        if (downloadUrl) {
            const success = await downloadDirect(downloadUrl, paper.title);
            if (success) {
                downloadedCount++;
                results.push({ ...paper, status: 'downloaded', downloadUrl });
            } else {
                failedCount++;
                results.push({ ...paper, status: 'failed' });
            }
        } else {
            console.log('  No download URL found - paper may not have PDF');
            skippedCount++;
            results.push({ ...paper, status: 'skipped', reason: 'no-download-url' });
        }

        // Rate limiting delay
        await new Promise(r => setTimeout(r, CONFIG.delayBetweenPapers));
    }

    // ============================================================
    // SUMMARY
    // ============================================================
    console.log('\n%c========================================', 'color: cyan; font-size: 16px');
    console.log('%c DOWNLOAD COMPLETE', 'color: cyan; font-size: 16px');
    console.log('%c========================================', 'color: cyan; font-size: 16px');
    console.log(`Downloaded: ${downloadedCount}`);
    console.log(`Skipped: ${skippedCount}`);
    console.log(`Failed: ${failedCount}`);
    console.log(`Total: ${papers.length}`);

    // Export results
    console.log('\n%cTo export results, run:', 'color: yellow');
    console.log('  copy(JSON.stringify(results, null, 2))');

    // Save results to window for easy access
    window.__cnkiDownloadResults = results;
    console.log('\nResults saved to window.__cnkiDownloadResults');
})();
