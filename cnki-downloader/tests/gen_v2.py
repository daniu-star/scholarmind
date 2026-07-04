"""Generate download page v2 - uses paper detail URLs, not download order URLs."""
import asyncio, re, os, json, time, webbrowser
from xml.etree import ElementTree as ET
import aiohttp

ALL_JOURNALS = {
    '新闻传播学': [('GJXW','国际新闻界'),('YANJ','新闻与传播研究'),('XWDX','新闻大学'),('DACB','当代传播')],
    '人工智能': [('MSSB','模式识别与人工智能'),('ZDHB','自动化学报'),('JFYZ','计算机研究与发展'),('PZKX','中国科学：信息科学')],
    '人类学': [('RLXB','人类学学报'),('MZYJ','民族研究'),('SHXJ','社会学研究'),('SHEH','社会')],
    '计算机科学': [('JSJX','计算机学报'),('RJXB','软件学报'),('JFYZ','计算机研究与发展'),('PZKX','中国科学：信息科学')],
    '化学': [('HXXB','化学学报'),('GDXH','高等学校化学学报'),('FXHX','分析化学'),('YJHU','有机化学')],
}

async def get_papers(cookies_raw, code, max_p=20):
    H = {'User-Agent':'Mozilla/5.0','Cookie':cookies_raw}
    async with aiohttp.ClientSession(headers=H) as s:
        async with s.get(f'https://rss.cnki.net/knavi/rss/{code}?pcode=CJFD,CCJD', ssl=False) as r:
            root = ET.fromstring(await r.text())
        papers = []
        for item in root.findall('.//item')[:max_p]:
            papers.append({
                'title':(item.findtext('title','')or'').strip(),
                'link':(item.findtext('link','')or'').strip(),
                'author':(item.findtext('author','')or'').strip(),
            })
        return papers

HTML_HEAD = '''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>CNKI Papers - {total} Papers</title>
<style>
*{{box-sizing:border-box}}
body{{font-family:"Microsoft YaHei",sans-serif;max-width:1000px;margin:0 auto;padding:15px;background:#f0f2f5}}
h1{{color:#1a1a2e;border-bottom:3px solid #1a73e8;padding-bottom:10px}}
.discipline h2{{color:#1a73e8;margin:15px 0 5px 0;padding:8px 15px;background:#e8f0fe;border-radius:8px}}
.paper{{border:1px solid #e0e0e0;margin:6px 0;padding:10px 15px;background:white;border-radius:6px}}
.paper h4{{margin:0 0 5px 0;font-size:14px;color:#333}}
.paper .meta{{color:#888;font-size:12px}}
.btn{{display:inline-block;padding:6px 16px;margin:3px 6px 3px 0;color:white;text-decoration:none;border-radius:4px;font-size:12px;border:none;cursor:pointer}}
.btn:hover{{opacity:0.85}}
.btn.detail{{background:#1a73e8}}
.status{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;margin-left:5px}}
.status.pending{{background:#fff3e0;color:#e65100}}
.status.opened{{background:#e8f5e9;color:#2e7d32}}
#panel{{position:fixed;top:0;right:0;width:260px;height:100vh;background:#1a1a2e;color:white;padding:20px;z-index:9999;overflow-y:auto}}
#panel h3{{margin-top:0}}
#panel .stat{{margin:8px 0;font-size:14px}}
#panel progress{{width:100%;height:20px}}
#panel button{{display:block;width:100%;padding:10px;margin:8px 0;border:none;border-radius:6px;font-size:14px;cursor:pointer;color:white}}
#panel .start-btn{{background:#1a73e8}}
#panel .stop-btn{{background:#ea4335}}
#panel .speed-btn{{background:#34a853}}
.inst{{background:#fff3cd;border:1px solid #ffc107;padding:12px;margin:10px 0;border-radius:6px;font-size:13px}}
</style></head><body>
<div id="panel">
<h3>Auto-Open Panel</h3>
<div class="stat">Total: <b>{total}</b> papers</div>
<div class="stat">Opened: <b id="cnt">0</b></div>
<progress id="prog" value="0" max="{total}"></progress>
<div class="stat" style="font-size:11px;margin-top:5px">Delay: <b id="delayDisplay">5</b>s each</div>
<br>
<button class="start-btn" onclick="startAuto()">START (or press S)</button>
<button class="stop-btn" onclick="stopAuto()">STOP (or press X)</button>
<button class="speed-btn" onclick="changeSpeed()">Speed: 5s</button>
<div style="margin-top:12px;font-size:11px;color:#aaa">
<p>Opens paper DETAIL pages.</p>
<p>Click PDF button on each page.</p>
<p>Allow popups!</p>
</div>
</div>
<h1>CNKI Paper Downloads - {total} Papers</h1>
<div class="inst">
<b>HOW:</b> Opens each paper detail page. On each page, click <b>"PDF下载"</b> to download.
Your browser has CNKI cookies so the detail pages will load correctly.
<br><b>Press S key to start auto-opening!</b>
</div>
'''

HTML_FOOT = '''
<script>
let opened=0;let current=0;let running=false;let delay=5000;let total={total};
function startAuto(){{if(running)return;running=true;processNext()}}
function stopAuto(){{running=false}}
function changeSpeed(){{var sp=[3000,5000,8000,12000];var lb=["3s","5s","8s","12s"];var cl=document.getElementById("delayDisplay").textContent;var i=lb.indexOf(cl);i=(i+1)%sp.length;delay=sp[i];document.getElementById("delayDisplay").textContent=lb[i];document.querySelector(".speed-btn").textContent="Speed: "+lb[i]}}
function processNext(){{if(!running||current>=total)return;var btn=document.querySelector("#p"+current+" .btn.detail");if(btn){{var w=window.open(btn.href,"_blank");markOpened(current);if(w)setTimeout(function(){{try{{w.close()}}catch(e){{}}}},20000)}}current++;document.getElementById("prog").value=current;if(running&&current<total)setTimeout(processNext,delay)}}
function markOpened(i){{var s=document.getElementById("s"+i);if(s){{s.textContent="opened";s.className="status opened"}}var p=document.getElementById("p"+i);if(p)p.style.opacity="0.5";opened++;document.getElementById("cnt").textContent=opened}}
document.addEventListener("keydown",function(e){{if(e.key==="s"||e.key==="S")startAuto();if(e.key==="x"||e.key==="X")stopAuto()}});
console.log("Ready! Press S to start.");
</script></body></html>
'''


async def main():
    raw = open('sessions/cnki_verified.json', 'r', encoding='utf-8').read().strip()
    all_papers = []

    for disc, journals in ALL_JOURNALS.items():
        for code, name in journals:
            papers = await get_papers(raw, code, 20)
            for p in papers:
                p['journal_code'] = code
                p['journal_name'] = name
                p['discipline'] = disc
            all_papers.extend(papers)
            print(f'{disc} - {name}: {len(papers)} papers')
            await asyncio.sleep(0.3)

    total = len(all_papers)
    print(f'Total: {total} papers')

    # Build HTML body
    html = HTML_HEAD.format(total=total)
    idx = 0
    for disc, journals in ALL_JOURNALS.items():
        html += f'<div class="discipline"><h2>{disc}</h2>'
        for code, name in journals:
            jp = [p for p in all_papers if p.get('journal_code') == code]
            if not jp:
                continue
            html += f'<h3>{name} ({len(jp)} papers)</h3>'
            for paper in jp:
                html += f'<div class="paper" id="p{idx}">'
                html += f'<h4>[{idx+1}] {paper["title"]}</h4>'
                html += f'<div class="meta">{name} | {paper.get("author","")}</div>'
                html += f'<a class="btn detail" href="{paper["link"]}" target="_blank" onclick="markOpened({idx})">Open Detail Page</a>'
                html += f'<span class="status pending" id="s{idx}">pending</span>'
                html += f'</div>'
                idx += 1
        html += '</div>'
    html += HTML_FOOT.format(total=idx)

    os.makedirs('downloads', exist_ok=True)
    path = 'downloads/all_papers_v2.html'
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f'Saved: {path}')
    webbrowser.open('file:///' + os.path.abspath(path))
    print('Opened in browser!')


if __name__ == '__main__':
    asyncio.run(main())
