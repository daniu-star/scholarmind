"""Generate a complete download page for ALL 5 disciplines x 4 journals = ALL papers."""
import asyncio, re, os, sys, time, json
from xml.etree import ElementTree as ET
import aiohttp

# All 20 journals
ALL_JOURNALS = {
    '新闻传播学': [
        ('GJXW', '国际新闻界'),
        ('YANJ', '新闻与传播研究'),
        ('XWDX', '新闻大学'),
        ('DACB', '当代传播'),
    ],
    '人工智能': [
        ('MSSB', '模式识别与人工智能'),
        ('ZDHB', '自动化学报'),
        ('JFYZ', '计算机研究与发展'),
        ('PZKX', '中国科学：信息科学'),
    ],
    '人类学': [
        ('RLXB', '人类学学报'),
        ('MZYJ', '民族研究'),
        ('SHXJ', '社会学研究'),
        ('SHEH', '社会'),
    ],
    '计算机科学': [
        ('JSJX', '计算机学报'),
        ('RJXB', '软件学报'),
        ('JFYZ', '计算机研究与发展'),
        ('PZKX', '中国科学：信息科学'),
    ],
    '化学': [
        ('HXXB', '化学学报'),
        ('GDXH', '高等学校化学学报'),
        ('FXHX', '分析化学'),
        ('YJHU', '有机化学'),
    ],
}


async def get_papers(cookies_raw, journal_code, max_papers=20):
    H = {'User-Agent': 'Mozilla/5.0', 'Cookie': cookies_raw}
    async with aiohttp.ClientSession(headers=H) as session:
        url = f'https://rss.cnki.net/knavi/rss/{journal_code}?pcode=CJFD,CCJD'
        try:
            async with session.get(url, ssl=False) as resp:
                root = ET.fromstring(await resp.text())
        except Exception:
            return []

        papers = []
        for item in root.findall('.//item')[:max_papers]:
            papers.append({
                'title': (item.findtext('title', '') or '').strip(),
                'link': (item.findtext('link', '') or '').strip(),
                'author': (item.findtext('author', '') or '').strip(),
            })
        return papers


async def get_download_urls(cookies_raw, paper_url):
    H = {'User-Agent': 'Mozilla/5.0', 'Cookie': cookies_raw}
    async with aiohttp.ClientSession(headers=H) as session:
        try:
            async with session.get(paper_url, ssl=False, allow_redirects=True) as resp:
                html = await resp.text()
            orders = re.findall(r'bar\.cnki\.net/bar/download/order\?id=([^"\'&\s]+)', html)
            result = {}
            if len(orders) >= 1:
                result['pdf'] = f'https://bar.cnki.net/bar/download/order?id={orders[0]}'
            if len(orders) >= 2:
                result['caj'] = f'https://bar.cnki.net/bar/download/order?id={orders[1]}'
            return result
        except Exception:
            return {}


def generate_html(all_papers):
    """Generate a comprehensive download HTML page with auto-download."""
    total = len(all_papers)
    papers_json = json.dumps(all_papers, ensure_ascii=False)

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>CNKI Full Download - {total} Papers</title>
<style>
* {{ box-sizing: border-box; }}
body {{ font-family: "Microsoft YaHei", sans-serif; max-width: 1000px; margin: 0 auto; padding: 15px; background: #f0f2f5; }}
h1 {{ color: #1a1a2e; border-bottom: 3px solid #1a73e8; padding-bottom: 10px; }}
.discipline {{ margin: 20px 0; }}
.discipline h2 {{ color: #1a73e8; margin: 15px 0 5px 0; padding: 8px 15px; background: #e8f0fe; border-radius: 8px; }}
.paper {{ border: 1px solid #e0e0e0; margin: 6px 0; padding: 10px 15px; background: white; border-radius: 6px; }}
.paper h4 {{ margin: 0 0 5px 0; font-size: 14px; color: #333; }}
.paper .meta {{ color: #888; font-size: 12px; }}
.paper .btns {{ margin-top: 6px; }}
.btn {{ display: inline-block; padding: 5px 14px; margin: 2px 6px 2px 0;
    background: #1a73e8; color: white; text-decoration: none; border-radius: 4px; font-size: 12px; border: none; cursor: pointer; }}
.btn:hover {{ opacity: 0.85; }}
.btn.pdf {{ background: #1a73e8; }}
.btn.caj {{ background: #ea4335; }}
.btn.detail {{ background: #34a853; }}
.status {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin-left: 5px; }}
.status.pending {{ background: #fff3e0; color: #e65100; }}
.status.done {{ background: #e8f5e9; color: #2e7d32; }}
.status.fail {{ background: #ffebee; color: #c62828; }}
#panel {{ position: fixed; top: 0; right: 0; width: 280px; height: 100vh;
    background: #1a1a2e; color: white; padding: 20px; z-index: 9999; overflow-y: auto; }}
#panel h3 {{ margin-top: 0; }}
#panel .stat {{ margin: 8px 0; font-size: 14px; }}
#panel progress {{ width: 100%; height: 20px; }}
#panel button {{ display: block; width: 100%; padding: 10px; margin: 8px 0;
    border: none; border-radius: 6px; font-size: 14px; cursor: pointer; color: white; }}
#panel .start-btn {{ background: #1a73e8; }}
#panel .stop-btn {{ background: #ea4335; }}
#panel .speed-btn {{ background: #34a853; }}
</style>
</head>
<body>

<div id="panel">
    <h3>Auto Download Panel</h3>
    <div class="stat">Total: <b>{total}</b> papers</div>
    <div class="stat">Downloaded: <b id="cnt">0</b></div>
    <div class="stat">Failed: <b id="fail">0</b></div>
    <progress id="prog" value="0" max="{total}"></progress>
    <div class="stat" style="font-size:11px;margin-top:5px">Delay: <b id="delayDisplay">4</b>s per paper</div>
    <br>
    <button class="start-btn" onclick="startAuto()">START AUTO DOWNLOAD</button>
    <button class="stop-btn" onclick="stopAuto()">STOP</button>
    <button class="speed-btn" onclick="changeSpeed()">Speed: 4s</button>
    <div style="margin-top:12px;font-size:11px;color:#aaa">
        <p>Papers will open in new tabs.</p>
        <p>Keep this window open.</p>
        <p>Allow popups for this page!</p>
        <p>Downloads go to your browser's default download folder.</p>
    </div>
</div>

<h1>CNKI Full-Text Paper Downloads</h1>
<p>Total: {total} papers across 5 disciplines | Generated: {time.strftime('%Y-%m-%d %H:%M')}</p>
<p style="color:#ea4335;font-weight:bold">IMPORTANT: Click "START AUTO DOWNLOAD" in the right panel to begin!</p>
'''

    idx = 0
    for discipline, journals in ALL_JOURNALS.items():
        html += f'<div class="discipline"><h2>{discipline}</h2>'
        for code, name in journals:
            journal_papers = [p for p in all_papers if p.get('journal_code') == code]
            if not journal_papers:
                continue
            html += f'<h3>{name} ({len(journal_papers)} papers)</h3>'
            for paper in journal_papers:
                dl = paper.get('download_urls', {})
                html += f'<div class="paper" id="p{idx}">'
                html += f'<h4>[{idx+1}] {paper["title"]}</h4>'
                html += f'<div class="meta">{name} | {paper.get("author", "")}</div>'
                html += f'<div class="btns">'
                if dl.get('pdf'):
                    html += f'<a class="btn pdf" href="{dl["pdf"]}" target="_blank">PDF Download</a>'
                if dl.get('caj'):
                    html += f'<a class="btn caj" href="{dl["caj"]}" target="_blank">CAJ Download</a>'
                html += f'<a class="btn detail" href="{paper["link"]}" target="_blank">Detail Page</a>'
                html += f'<span class="status pending" id="s{idx}">pending</span>'
                html += f'</div></div>'
                idx += 1
        html += '</div>'

    html += f'''
<script>
let downloaded = 0;
let failed = 0;
let current = 0;
let total = {idx};
let running = false;
let delay = 4000;
let timer = null;

function startAuto() {{
    if (running) return;
    running = true;
    console.log('Auto download started!');
    processNext();
}}

function stopAuto() {{
    running = false;
    if (timer) clearTimeout(timer);
    console.log('Auto download stopped at paper ' + current);
}}

function changeSpeed() {{
    const speeds = [2000, 4000, 6000, 8000, 10000];
    const labels = ['2s', '4s', '6s', '8s', '10s'];
    const currentLabel = document.getElementById('delayDisplay').textContent;
    let idx = labels.indexOf(currentLabel);
    idx = (idx + 1) % speeds.length;
    delay = speeds[idx];
    document.getElementById('delayDisplay').textContent = labels[idx];
    document.querySelector('.speed-btn').textContent = 'Speed: ' + labels[idx];
    console.log('Speed changed to ' + labels[idx]);
}}

function processNext() {{
    if (!running || current >= total) {{
        if (current >= total) console.log('ALL DONE!');
        return;
    }}

    const paper = document.getElementById('p' + current);
    if (!paper) {{ current++; processNext(); return; }}

    // Find PDF button
    const pdfBtn = paper.querySelector('.btn.pdf');
    if (pdfBtn) {{
        // Open download in new tab
        const win = window.open(pdfBtn.href, '_blank');
        if (win) {{
            markDone(current);
            // Close the tab after a delay
            setTimeout(() => {{ try {{ win.close(); }} catch(e) {{}} }}, 8000);
        }} else {{
            markFailed(current, 'popup blocked');
        }}
    }} else {{
        markFailed(current, 'no PDF URL');
    }}

    current++;
    document.getElementById('prog').value = current;

    if (running && current < total) {{
        timer = setTimeout(processNext, delay);
    }}
}}

function markDone(i) {{
    const status = document.getElementById('s' + i);
    if (status) {{ status.textContent = 'downloaded'; status.className = 'status done'; }}
    const paper = document.getElementById('p' + i);
    if (paper) paper.style.opacity = '0.5';
    downloaded++;
    document.getElementById('cnt').textContent = downloaded;
}}

function markFailed(i, reason) {{
    const status = document.getElementById('s' + i);
    if (status) {{ status.textContent = 'failed: ' + reason; status.className = 'status fail'; }}
    failed++;
    document.getElementById('fail').textContent = failed;
}}

// Keyboard shortcut: press 'S' to start
document.addEventListener('keydown', function(e) {{
    if (e.key === 's' || e.key === 'S') startAuto();
    if (e.key === 'x' || e.key === 'X') stopAuto();
}});

console.log('Download page ready. Press S to start auto-download.');
console.log('Total papers: ' + total);
</script>
</body></html>'''

    return html


async def main():
    raw = open('sessions/cnki_verified.json', 'r', encoding='utf-8').read().strip()
    all_papers = []
    total = 0
    failed_journals = 0

    for discipline, journals in ALL_JOURNALS.items():
        for code, name in journals:
            print(f'{discipline} - {name} ({code})...', end=' ')
            papers = await get_papers(raw, code, max_papers=20)
            print(f'{len(papers)} papers')

            for paper in papers:
                paper['journal_code'] = code
                paper['journal_name'] = name
                paper['discipline'] = discipline
                dl = await get_download_urls(raw, paper['link'])
                paper['download_urls'] = dl
                all_papers.append(paper)
                await asyncio.sleep(0.2)

            total += len(papers)

    print(f'\nTotal: {total} papers from {20 - failed_journals} journals')

    # Save JSON
    os.makedirs('downloads', exist_ok=True)
    with open('downloads/all_papers.json', 'w', encoding='utf-8') as f:
        json.dump(all_papers, f, ensure_ascii=False, indent=2)

    # Generate HTML
    html = generate_html(all_papers)
    html_path = 'downloads/all_papers_download.html'
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f'HTML generated: {html_path}')
    print(f'Total papers in HTML: {total}')

    # Open in browser
    abs_path = os.path.abspath(html_path)
    import webbrowser
    webbrowser.open(f'file:///{abs_path}')
    print('Opened in browser. Press S to start auto-download!')


if __name__ == '__main__':
    asyncio.run(main())
