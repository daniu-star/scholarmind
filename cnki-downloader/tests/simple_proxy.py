"""Ultra-simple proxy: inject auto-download JS into CNKI pages."""
import http.server, json, asyncio, aiohttp, urllib.parse, os, webbrowser, sys

PORT = 8766
COOKIES = open('sessions/cnki_verified.json','r',encoding='utf-8').read().strip()

# Paper list (pre-generated)
PAPERS = json.load(open('downloads/all_papers.json','r',encoding='utf-8'))
print(f'Loaded {len(PAPERS)} papers')

AUTO_CLICK = '''<script>
(function(){
console.log("[AUTO] Looking for download button...");
var tries=0;
function find(){
tries++;
var btns=document.querySelectorAll("a");
var pdf=null;
for(var i=0;i<btns.length;i++){
var t=(btns[i].textContent||"").trim();
if(t.indexOf("PDF")>=0&&t.indexOf("下载")>=0){pdf=btns[i];break}
}
if(!pdf){for(var i=0;i<btns.length;i++){var t=(btns[i].textContent||"").trim();if(t.indexOf("PDF")>=0){pdf=btns[i];break}}}
if(!pdf){for(var i=0;i<btns.length;i++){var h=(btns[i].href||"").toLowerCase();if(h.indexOf("download/order")>=0){pdf=btns[i];break}}}
if(pdf){
console.log("[AUTO] Clicking: "+pdf.textContent.trim());
var d=document.createElement("div");d.style.cssText="position:fixed;top:0;left:0;right:0;background:#1a73e8;color:white;padding:15px;z-index:99999;text-align:center;font-size:16px;font-weight:bold";d.textContent="Auto-clicking PDF download...";document.body.appendChild(d);
setTimeout(function(){pdf.click();d.textContent="Download started! Closing tab...";setTimeout(function(){window.close()},8000)},1500);
}else if(tries<15){setTimeout(find,1500)}
}
setTimeout(find,2000);
})();
</script>'''

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path
        if path == '/' or path == '/index.html':
            self._serve_page()
        elif path.startswith('/p/'):
            self._proxy(path[3:])
        else:
            self.send_response(404); self.end_headers(); self.wfile.write(b'404')

    def _serve_page(self):
        html = f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>CNKI Auto Download - {len(PAPERS)} Papers</title>
<style>
*{{box-sizing:border-box}}body{{font-family:"Microsoft YaHei",sans-serif;max-width:950px;margin:0 auto;padding:15px;background:#f0f2f5}}
h1{{color:#1a1a2e;border-bottom:3px solid #1a73e8;padding-bottom:10px}}
.paper{{border:1px solid #e0e0e0;margin:4px 0;padding:8px 12px;background:white;border-radius:6px;font-size:13px}}
.paper h4{{margin:0 0 3px 0;font-size:13px;color:#333}}
.paper .meta{{color:#888;font-size:11px}}
.btn{{display:inline-block;padding:4px 12px;margin:2px 4px 2px 0;color:white;text-decoration:none;border-radius:4px;font-size:11px}}
.btn.pdf{{background:#1a73e8}}.btn.caj{{background:#ea4335}}.status{{display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;margin-left:4px}}
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
<div style="margin-top:10px;font-size:10px;color:#aaa">Each tab auto-clicks PDF download!<br>Allow popups!<br>PDFs go to browser download folder.</div>
</div>
<h1>CNKI Auto-Download</h1>
<div class="inst"><b>AUTO MODE:</b> Each opened paper page will <b>automatically find and click</b> the PDF download button. No manual clicking needed! Press <b>S</b> to start.</div>
'''
        for i, p in enumerate(PAPERS):
            enc = urllib.parse.quote(p['link'], safe='')
            html += f'<div class="paper" id="pp{i}"><h4>[{i+1}] {p["title"]}</h4>'
            html += f'<div class="meta">{p.get("journal_name","")} | {p.get("author","")}</div>'
            html += f'<a class="btn pdf" href="/p/{enc}" target="_blank" onclick="m({i})">PDF Download</a>'
            html += f'<span class="status pending" id="ss{i}">pending</span></div>'

        html += f'''<script>
var o=0,c=0,r=false,d=5000,t={len(PAPERS)};
function go(){{if(r)return;r=true;n()}}function stop(){{r=false}}
function cs(){{var s=[3000,5000,8000,12000];var l=["3s","5s","8s","12s"];var cl=document.getElementById("dd").textContent;var i=l.indexOf(cl);i=(i+1)%s.length;d=s[i];document.getElementById("dd").textContent=l[i];document.querySelector(".speed").textContent="Speed: "+l[i]}}
function n(){{if(!r||c>=t)return;var b=document.querySelector("#pp"+c+" .btn.pdf");if(b){{var w=window.open(b.href,"_blank");m(c);setTimeout(function(){{try{{w.close()}}catch(e){{}}}},25000)}}c++;document.getElementById("prog").value=c;if(r&&c<t)setTimeout(n,d)}}
function m(i){{var s=document.getElementById("ss"+i);if(s){{s.textContent="opened";s.className="status opened"}}var p=document.getElementById("pp"+i);if(p)p.style.opacity="0.5";o++;document.getElementById("cnt").textContent=o}}
document.addEventListener("keydown",function(e){{if(e.key==="s"||e.key==="S")go();if(e.key==="x"||e.key==="X")stop()}});
console.log("Press S to start auto-download");</script></body></html>'''
        self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Content-Length',str(len(html.encode('utf-8')))); self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def _proxy(self, url):
        try:
            decoded = urllib.parse.unquote(url)
            print(f'Proxy: {decoded[:100]}')
            asyncio.run(self._fetch(decoded))
        except Exception as e:
            print(f'Proxy error: {e}')
            self.send_response(502); self.end_headers(); self.wfile.write(str(e).encode())

    async def _fetch(self, url):
        H = {'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
             'Accept':'text/html,application/xhtml+xml,*/*','Accept-Language':'zh-CN,zh;q=0.9',
             'Cookie':COOKIES}
        async with aiohttp.ClientSession(headers=H) as s:
            async with s.get(url, ssl=False, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=20)) as r:
                body = await r.read()
                ct = r.headers.get('Content-Type','text/html')
                body_s = body.decode('utf-8','replace')
                if '</body>' in body_s:
                    body_s = body_s.replace('</body>', AUTO_CLICK+'</body>')
                elif '</head>' in body_s:
                    body_s = body_s.replace('</head>', AUTO_CLICK+'</head>')
                body = body_s.encode('utf-8')
                self.send_response(r.status); self.send_header('Content-Type',ct)
                self.send_header('Content-Length',str(len(body))); self.end_headers()
                self.wfile.write(body)

    def log_message(self, *args): pass

if __name__ == '__main__':
    print(f'Proxy server: http://localhost:{PORT}/')
    webbrowser.open(f'http://localhost:{PORT}/')
    http.server.HTTPServer(('127.0.0.1',PORT), Handler).serve_forever()
