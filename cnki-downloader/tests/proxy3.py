"""Ultra-minimal CNKI proxy with auto-click injection."""
import http.server, json, asyncio, aiohttp, urllib.parse, os, webbrowser, sys, threading

PORT = 8766
COOKIES = open(os.path.join(os.path.dirname(__file__), '..', 'sessions', 'cnki_verified.json'), 'r', encoding='utf-8').read().strip()
PAPERS = json.load(open(os.path.join(os.path.dirname(__file__), '..', 'downloads', 'all_papers.json'), 'r', encoding='utf-8'))
SAFE = {'title': 'CNKI Download', 'total': len(PAPERS), 'papers': [], 'port': PORT}

for i, p in enumerate(PAPERS):
    SAFE['papers'].append({
        'i': i, 't': p['title'], 'a': p.get('author',''), 'j': p.get('journal_name',''),
        'u': p['link']
    })

# Pre-generate the HTML page
PAGE_HTML = ''
for i, p in enumerate(SAFE['papers']):
    enc = urllib.parse.quote(p['u'], safe='')
    PAGE_HTML += f'<div class="paper" id="pp{i}"><h4>[{i+1}] {p["t"]}</h4>'
    PAGE_HTML += f'<div class="meta">{p["j"]} | {p["a"]}</div>'
    PAGE_HTML += f'<a class="btn pdf" href="/p/{enc}" target="_blank" onclick="m({i})">PDF Download</a>'
    PAGE_HTML += f'<span class="status pending" id="ss{i}">pending</span></div>\n'

CTRL = f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><title>CNKI Auto</title>
<style>*{{box-sizing:border-box}}body{{font-family:"Microsoft YaHei",sans-serif;max-width:950px;margin:0 auto;padding:15px;background:#f0f2f5}}
h1{{color:#1a1a2e;border-bottom:3px solid #1a73e8;padding-bottom:10px}}
.paper{{border:1px solid #e0e0e0;margin:4px 0;padding:8px 12px;background:white;border-radius:6px;font-size:13px}}
.paper h4{{margin:0 0 3px 0;font-size:13px;color:#333}}.paper .meta{{color:#888;font-size:11px}}
.btn{{display:inline-block;padding:4px 12px;margin:2px 4px 2px 0;color:white;text-decoration:none;border-radius:4px;font-size:11px}}
.btn.pdf{{background:#1a73e8}}.status{{display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;margin-left:4px}}
.status.pending{{background:#fff3e0;color:#e65100}}.status.opened{{background:#e8f5e9;color:#2e7d32}}
#panel{{position:fixed;top:0;right:0;width:250px;height:100vh;background:#1a1a2e;color:white;padding:15px;z-index:9999;overflow-y:auto}}
#panel h3{{margin:0 0 10px 0;font-size:16px}}#panel .stat{{margin:6px 0;font-size:13px}}
#panel progress{{width:100%;height:16px}}#panel button{{display:block;width:100%;padding:8px;margin:6px 0;border:none;border-radius:5px;font-size:13px;cursor:pointer;color:white}}
#panel .start{{background:#1a73e8}}#panel .stop{{background:#ea4335}}#panel .speed{{background:#34a853}}
.inst{{background:#e8f5e9;border:1px solid #4caf50;padding:10px;margin:8px 0;border-radius:6px;font-size:12px}}
</style></head><body>
<div id="panel"><h3>Auto Download</h3>
<div class="stat">Papers: <b>{len(PAPERS)}</b></div>
<div class="stat">Opened: <b id="cnt">0</b></div>
<progress id="prog" value="0" max="{len(PAPERS)}"></progress>
<div class="stat" style="font-size:11px">Delay: <b id="dd">5</b>s</div>
<button class="start" onclick="go()">START (S)</button>
<button class="stop" onclick="stop()">STOP (X)</button>
<button class="speed" onclick="cs()">Speed: 5s</button>
<div style="margin-top:10px;font-size:10px;color:#aaa">Auto-injects PDF click JS!</div></div>
<h1>CNKI Auto-Download (Proxy Mode)</h1>
<div class="inst"><b>FULL AUTO:</b> Each tab auto-clicks PDF download. Press <b>S</b> to start. PDFs go to browser downloads.</div>
{PAGE_HTML}
<script>
var o=0,c=0,r=false,d=5000,t={len(PAPERS)};
function go(){{if(r)return;r=true;n()}}function stop(){{r=false}}
function cs(){{var s=[3000,5000,8000,12000];var l=["3s","5s","8s","12s"];var cl=document.getElementById("dd").textContent;var i=l.indexOf(cl);i=(i+1)%s.length;d=s[i];document.getElementById("dd").textContent=l[i];document.querySelector(".speed").textContent="Speed: "+l[i]}}
function n(){{if(!r||c>=t)return;var b=document.querySelector("#pp"+c+" .btn.pdf");if(b){{var w=window.open(b.href,"_blank");m(c);setTimeout(function(){{try{{w.close()}}catch(e){{}}}},25000)}}c++;document.getElementById("prog").value=c;if(r&&c<t)setTimeout(n,d)}}
function m(i){{var s=document.getElementById("ss"+i);if(s){{s.textContent="opened";s.className="status opened"}}var p=document.getElementById("pp"+i);if(p)p.style.opacity="0.5";o++;document.getElementById("cnt").textContent=o}}
document.addEventListener("keydown",function(e){{if(e.key==="s"||e.key==="S")go();if(e.key==="x"||e.key==="X")stop()}});
</script></body></html>'''

AUTO_JS = '<script>(function(){var t=0;function f(){t++;var b=document.querySelectorAll("a");var p=null;for(var i=0;i<b.length;i++){var x=(b[i].textContent||"").trim();if(x.indexOf("PDF")>=0&&x.indexOf("下载")>=0){p=b[i];break}}if(!p){for(var i=0;i<b.length;i++){if((b[i].textContent||"").trim().indexOf("PDF")>=0){p=b[i];break}}}if(!p){for(var i=0;i<b.length;i++){if((b[i].href||"").toLowerCase().indexOf("download/order")>=0){p=b[i];break}}}if(p){var d=document.createElement("div");d.style.cssText="position:fixed;top:0;left:0;right:0;background:#1a73e8;color:white;padding:15px;z-index:99999;text-align:center;font-size:16px;font-weight:bold";d.textContent="Auto-clicking: "+p.textContent.trim();document.body.appendChild(d);setTimeout(function(){p.click();d.textContent="Download started! Closing tab...";setTimeout(function(){window.close()},8000)},1500)}else if(t<15){setTimeout(f,1500)}}setTimeout(f,2000)})();</script>'


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        p = self.path
        if p == '/' or p == '/index.html':
            b = CTRL.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        elif p.startswith('/p/'):
            url = urllib.parse.unquote(p[3:])
            print(f'Proxy: {url[:100]}')
            try:
                asyncio.run(self._fetch(url))
            except Exception as e:
                print(f'Error: {e}')
                self.send_response(502)
                self.end_headers()
                self.wfile.write(str(e).encode())
        else:
            self.send_response(404)
            self.end_headers()

    async def _fetch(self, url):
        HDR = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Cookie': COOKIES,
        }
        async with aiohttp.ClientSession(headers=HDR) as s:
            async with s.get(url, ssl=False, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=20)) as r:
                body = await r.read()
                ct = r.headers.get('Content-Type', 'text/html')
                body_s = body.decode('utf-8', 'replace')
                if '</body>' in body_s:
                    body_s = body_s.replace('</body>', f'{AUTO_JS}</body>')
                elif '</head>' in body_s:
                    body_s = body_s.replace('</head>', f'{AUTO_JS}</head>')
                body = body_s.encode('utf-8')
                self.send_response(r.status)
                self.send_header('Content-Type', ct)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    print(f'CNKI Proxy: http://localhost:{PORT}/')
    webbrowser.open(f'http://localhost:{PORT}/')
    srv = http.server.HTTPServer(('127.0.0.1', PORT), H)
    print(f'Running on port {PORT}...')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()
        print('Stopped')
