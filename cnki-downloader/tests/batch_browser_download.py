"""Batch open CNKI paper detail pages in user's real browser for download.

The user's real browser has working CNKI cookies and trusted certificates.
This script generates the paper list, then opens each paper detail page
in the browser. The user clicks "PDF下载" on each page to download.

USAGE: python tests/batch_browser_download.py [--auto]
  --auto: Also try to auto-click the download button (if page allows JS access)
"""

import asyncio, re, os, sys, time, webbrowser, json
from pathlib import Path
from xml.etree import ElementTree as ET
import aiohttp


async def get_papers(cookies_raw, journal_code, max_papers=20):
    """Get paper list from RSS feed."""
    H = {'User-Agent': 'Mozilla/5.0', 'Cookie': cookies_raw}
    async with aiohttp.ClientSession(headers=H) as session:
        url = f'https://rss.cnki.net/knavi/rss/{journal_code}?pcode=CJFD,CCJD'
        async with session.get(url, ssl=False) as resp:
            root = ET.fromstring(await resp.text())

        papers = []
        for item in root.findall('.//item')[:max_papers]:
            papers.append({
                'title': (item.findtext('title', '') or '').strip(),
                'link': (item.findtext('link', '') or '').strip(),
                'author': (item.findtext('author', '') or '').strip(),
            })
        return papers


async def get_download_urls(cookies_raw, paper_url):
    """Get download URLs from paper detail page."""
    H = {'User-Agent': 'Mozilla/5.0', 'Cookie': cookies_raw}
    async with aiohttp.ClientSession(headers=H) as session:
        async with session.get(paper_url, ssl=False, allow_redirects=True) as resp:
            html = await resp.text()

        # Extract download order URLs
        orders = re.findall(r'bar\.cnki\.net/bar/download/order\?id=([^"\'&\s]+)', html)
        result = {}
        if len(orders) >= 1:
            result['pdf'] = f'https://bar.cnki.net/bar/download/order?id={orders[0]}'
        if len(orders) >= 2:
            result['caj'] = f'https://bar.cnki.net/bar/download/order?id={orders[1]}'
        return result


def main():
    raw = open('sessions/cnki_verified.json', 'r', encoding='utf-8').read().strip()

    # Config
    JOURNALS = [
        ('GJXW', '国际新闻界', '新闻传播学'),
        ('YANJ', '新闻与传播研究', '新闻传播学'),
        ('XWDX', '新闻大学', '新闻传播学'),
        ('DACB', '当代传播', '新闻传播学'),
    ]

    auto_mode = '--auto' in sys.argv
    papers_per_journal = 10  # Start with 10 per journal

    print('=' * 60)
    print('CNKI Batch Browser Download')
    print('=' * 60)
    print(f'Mode: {"AUTO" if auto_mode else "MANUAL"}')
    print(f'Papers per journal: {papers_per_journal}')
    print(f'Journals: {len(JOURNALS)}')
    print()

    async def run():
        all_papers = []

        for code, name, discipline in JOURNALS:
            print(f'\n--- {name} ({code}) ---')
            papers = await get_papers(raw, code, papers_per_journal)
            print(f'  Found {len(papers)} papers')

            for paper in papers:
                print(f'  Getting download URL: {paper["title"][:50]}...')
                dl_urls = await get_download_urls(raw, paper['link'])
                paper['download_urls'] = dl_urls
                paper['journal'] = name
                paper['discipline'] = discipline
                all_papers.append(paper)
                await asyncio.sleep(0.3)

        # Save paper list
        with open('downloads/paper_list.json', 'w', encoding='utf-8') as f:
            json.dump(all_papers, f, ensure_ascii=False, indent=2)
        print(f'\nSaved {len(all_papers)} papers to downloads/paper_list.json')

        # Generate HTML page with all download links
        html_lines = [
            '<html><head><meta charset="utf-8"><title>CNKI Paper Downloads</title>',
            '<style>',
            'body{font-family:Microsoft YaHei,sans-serif;max-width:900px;margin:20px auto;padding:20px;background:#f5f5f5}',
            '.paper{border:1px solid #ddd;margin:10px 0;padding:15px;background:white;border-radius:8px}',
            '.paper h3{margin:0 0 8px 0;color:#333}',
            '.paper .meta{color:#666;font-size:13px;margin:5px 0}',
            '.paper .btn{display:inline-block;padding:8px 16px;margin:5px 5px 0 0;',
            'background:#1a73e8;color:white;text-decoration:none;border-radius:4px;font-size:14px}',
            '.paper .btn.caj{background:#ea4335}',
            '.paper .btn.detail{background:#34a853}',
            '.paper .status{display:inline-block;margin-left:10px;padding:4px 8px;border-radius:4px;font-size:12px}',
            '.paper .status.done{background:#e8f5e9;color:#2e7d32}',
            '.paper .status.pending{background:#fff3e0;color:#e65100}',
            '#counter{position:fixed;top:10px;right:10px;background:#333;color:white;padding:10px 15px;border-radius:8px;font-size:16px}',
            '#progress{position:fixed;top:60px;right:10px;background:white;padding:10px 15px;border-radius:8px;border:1px solid #ddd;font-size:14px;max-width:250px}',
            '</style></head><body>',
            '<h1>CNKI Paper Download List</h1>',
            f'<p>Total: {len(all_papers)} papers | Generated: {time.strftime("%Y-%m-%d %H:%M")}</p>',
            '<p><b>Instructions:</b> Click each blue button to download. Green = already clicked.</p>',
            '<div id="counter">Downloaded: <span id="count">0</span>/' + str(len(all_papers)) + '</div>',
            '<div id="progress"></div>',
        ]

        for i, paper in enumerate(all_papers):
            dl = paper.get('download_urls', {})
            html_lines.append(f'<div class="paper" id="paper{i}">')
            html_lines.append(f'<h3>[{i+1}] {paper["title"]}</h3>')
            html_lines.append(f'<div class="meta">Journal: {paper.get("journal","")} | Authors: {paper.get("author","")}</div>')

            if dl.get('pdf'):
                html_lines.append(
                    f'<a class="btn" href="{dl["pdf"]}" target="_blank" '
                    f'onclick="markDone({i},\'pdf\')">PDF Download</a>'
                )
            if dl.get('caj'):
                html_lines.append(
                    f'<a class="btn caj" href="{dl["caj"]}" target="_blank" '
                    f'onclick="markDone({i},\'caj\')">CAJ Download</a>'
                )
            html_lines.append(
                f'<a class="btn detail" href="{paper["link"]}" target="_blank">Paper Detail</a>'
            )
            html_lines.append(f'<span class="status pending" id="status{i}">pending</span>')
            html_lines.append('</div>')

        # JavaScript for tracking
        html_lines.append('''
        <script>
        let downloaded = 0;
        const total = ''' + str(len(all_papers)) + ''';
        const progress = [];

        function markDone(i, format) {
            const status = document.getElementById('status' + i);
            if (status) {
                status.textContent = 'downloaded (' + format + ')';
                status.className = 'status done';
            }
            const paper = document.getElementById('paper' + i);
            if (paper) paper.style.opacity = '0.6';

            if (!progress.includes(i)) {
                progress.push(i);
                downloaded = progress.length;
                document.getElementById('count').textContent = downloaded;
                document.getElementById('progress').innerHTML =
                    'Completed: ' + downloaded + '/' + total +
                    '<br><progress value="' + downloaded + '" max="' + total + '"></progress>';
            }
        }

        // Auto-open first few papers
        let autoIndex = 0;
        function autoOpen() {
            if (autoIndex >= Math.min(5, total)) return;
            const paper = document.getElementById('paper' + autoIndex);
            if (paper) {
                const pdfBtn = paper.querySelector('.btn');
                if (pdfBtn) {
                    markDone(autoIndex, 'pdf');
                    pdfBtn.click();
                }
            }
            autoIndex++;
            if (autoIndex < Math.min(5, total)) {
                setTimeout(autoOpen, 3000);
            }
        }
        // Uncomment to enable auto-open:
        // setTimeout(autoOpen, 2000);
        </script>
        ''')
        html_lines.append('</body></html>')

        html_path = 'downloads/paper_download_page.html'
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(html_lines))

        print(f'\nGenerated download page: {html_path}')
        print(f'Opening in browser...')

        # Open the download page in browser
        abs_path = os.path.abspath(html_path)
        webbrowser.open(f'file:///{abs_path}')

        print('\nThe download page has been opened in your browser.')
        print('Click each blue "PDF Download" button to download the paper.')
        print('The progress tracker will show which papers are done.')

    asyncio.run(run())


if __name__ == '__main__':
    main()
