"""Local proxy server: fetches CNKI pages with cookies, injects auto-download JS.

The browser connects to localhost (no SSL issues).
The server proxies CNKI requests with valid cookies.
JS is injected to auto-click the PDF download button on paper detail pages.
"""

import http.server, os, sys, re, json, threading, time, urllib.parse
import asyncio
import aiohttp

PORT = 8766
COOKIES_RAW = open('sessions/cnki_verified.json', 'r', encoding='utf-8').read().strip()

# Auto-click JavaScript to inject into CNKI pages
AUTO_CLICK_JS = '''
<script>
(function() {
    console.log("[CNKI Auto-Download] Looking for download button...");
    var attempts = 0;
    var maxAttempts = 20;

    function findAndClick() {
        attempts++;
        var links = document.querySelectorAll("a");
        var pdfBtn = null;

        for (var i = 0; i < links.length; i++) {
            var text = (links[i].textContent || "").trim();
            if (text.indexOf("PDF") >= 0 && text.indexOf("下载") >= 0) {
                pdfBtn = links[i];
                break;
            }
        }

        if (!pdfBtn) {
            for (var i = 0; i < links.length; i++) {
                var text = (links[i].textContent || "").trim();
                if (text.indexOf("PDF") >= 0 || text.indexOf("CAJ") >= 0) {
                    pdfBtn = links[i];
                    break;
                }
            }
        }

        if (!pdfBtn) {
            for (var i = 0; i < links.length; i++) {
                var text = (links[i].textContent || "").trim().toLowerCase();
                var href = (links[i].href || "").toLowerCase();
                if (href.indexOf("download") >= 0 || href.indexOf("order") >= 0) {
                    pdfBtn = links[i];
                    break;
                }
            }
        }

        if (pdfBtn) {
            console.log("[CNKI Auto-Download] Found: " + pdfBtn.textContent.trim());
            console.log("[CNKI Auto-Download] URL: " + pdfBtn.href);

            // Show a visible indicator
            var indicator = document.createElement("div");
            indicator.style.cssText = "position:fixed;top:10px;left:10px;background:#1a73e8;color:white;padding:15px 25px;z-index:99999;border-radius:8px;font-size:16px;font-weight:bold;box-shadow:0 4px 12px rgba(0,0,0,0.3)";
            indicator.textContent = "Auto-clicking PDF download...";
            document.body.appendChild(indicator);

            // Click the download button
            setTimeout(function() {
                pdfBtn.click();
                indicator.textContent = "Download started! Closing tab in 8s...";
                setTimeout(function() { window.close(); }, 8000);
            }, 1000);
        } else if (attempts < maxAttempts) {
            console.log("[CNKI Auto-Download] Button not found yet, retrying... (" + attempts + "/" + maxAttempts + ")");
            setTimeout(findAndClick, 1000);
        } else {
            console.log("[CNKI Auto-Download] No download button found after " + maxAttempts + " attempts");
        }
    }

    // Start after page loads
    if (document.readyState === "complete") {
        setTimeout(findAndClick, 2000);
    } else {
        window.addEventListener("load", function() {
            setTimeout(findAndClick, 2000);
        });
    }
})();
</script>
'''

# CSS to highlight download buttons
HIGHLIGHT_CSS = '''
<style>
/* Highlight download buttons */
a[href*="download"], a[href*="order"] {
    outline: 3px solid #ff0000 !important;
    background: #ffeb3b !important;
    animation: pulse 1s infinite;
}
@keyframes pulse {
    0%, 100% { outline-color: #ff0000; }
    50% { outline-color: #ff6600; }
}
</style>
'''


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path
        parsed = urllib.parse.urlparse(path)

        # Handle root - show control page
        if path == '/' or path == '/index.html':
            self._serve_control_page()
            return

        # Handle /proxy/ - proxy CNKI URLs
        if path.startswith('/proxy/'):
            target_url = path[7:]  # Remove /proxy/ prefix
            if not target_url.startswith('http'):
                target_url = 'https://' + target_url
            print(f'Proxying: {target_url[:120]}')
            asyncio.run(self._proxy_request(target_url))
            return

        # Serve static files
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b'Not found')

    def _serve_control_page(self):
        """Serve the main control page with all paper links pointing to /proxy/ URLs."""
        # Generate paper list
        papers = asyncio.run(self._get_papers())

        html = f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>CNKI Auto-Download (Proxy Mode) - {len(papers)} Papers</title>
<style>
*{{box-sizing:border-box}}
body{{font-family:"Microsoft YaHei",sans-serif;max-width:1000px;margin:0 auto;padding:15px;background:#f0f2f5}}
h1{{color:#1a1a2e;border-bottom:3px solid #1a73e8;padding-bottom:10px}}
.paper{{border:1px solid #e0e0e0;margin:6px 0;padding:10px 15px;background:white;border-radius:6px}}
.paper h4{{margin:0 0 5px 0;font-size:14px;color:#333}}
.paper .meta{{color:#888;font-size:12px}}
.btn{{display:inline-block;padding:6px 16px;margin:3px 6px 3px 0;color:white;text-decoration:none;border-radius:4px;font-size:12px;border:none;cursor:pointer}}
.btn:hover{{opacity:0.85}}
.btn.pdf{{background:#1a73e8}}
.btn.caj{{background:#ea4335}}
.status{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;margin-left:5px}}
.status.pending{{background:#fff3e0;color:#e65100}}
.status.opened{{background:#e8f5e9;color:#2e7d32}}
#panel{{position:fixed;top:0;right:0;width:280px;height:100vh;background:#1a1a2e;color:white;padding:20px;z-index:9999;overflow-y:auto}}
#panel h3{{margin-top:0}}
#panel .stat{{margin:8px 0;font-size:14px}}
#panel progress{{width:100%;height:20px}}
#panel button{{display:block;width:100%;padding:10px;margin:8px 0;border:none;border-radius:6px;font-size:14px;cursor:pointer;color:white}}
#panel .start-btn{{background:#1a73e8}}
#panel .stop-btn{{background:#ea4335}}
#panel .speed-btn{{background:#34a853}}
.inst{{background:#e8f5e9;border:1px solid #4caf50;padding:12px;margin:10px 0;border-radius:6px;font-size:13px}}
</style></head><body>
<div id="panel">
<h3>Auto-Download Panel</h3>
<div class="stat">Total: <b>{len(papers)}</b> papers</div>
<div class="stat">Opened: <b id="cnt">0</b></div>
<progress id="prog" value="0" max="{len(papers)}"></progress>
<div class="stat" style="font-size:11px;margin-top:5px">Delay: <b id="delayDisplay">6</b>s each</div>
<br>
<button class="start-btn" onclick="startAuto()">START (or press S)</button>
<button class="stop-btn" onclick="stopAuto()">STOP (or press X)</button>
<button class="speed-btn" onclick="changeSpeed()">Speed: 6s</button>
<div style="margin-top:12px;font-size:11px;color:#aaa">
<p>Opens paper detail pages via PROXY.</p>
<p>Proxy injects auto-click JS!</p>
<p>Each page auto-clicks PDF download.</p>
<p>Allow popups!</p>
</div>
</div>
<h1>CNKI Auto-Download (Proxy Mode)</h1>
<div class="inst">
<b>HOW IT WORKS:</b> Each link goes through a LOCAL PROXY that injects JavaScript.
When the paper detail page opens, the injected JS <b>automatically finds and clicks</b>
the "PDF下载" button. No manual clicking needed!
<br><b>Press S to start!</b> | Server: localhost:{PORT}
</div>'''

        for i, paper in enumerate(papers):
            proxy_url = f'/proxy/{urllib.parse.quote(paper["link"], safe="")}'
            html += f'<div class="paper" id="p{i}">'
            html += f'<h4>[{i+1}] {paper["title"]}</h4>'
            html += f'<div class="meta">{paper.get("journal_name","")} | {paper.get("author","")}</div>'
            html += f'<a class="btn pdf" href="{proxy_url}" target="_blank" onclick="markOpened({i})">Auto-Download PDF</a>'
            html += f'<span class="status pending" id="s{i}">pending</span>'
            html += f'</div>'

        html += f'''
<script>
var opened=0;var current=0;var running=false;var delay=6000;var total={len(papers)};
function startAuto(){{if(running)return;running=true;processNext()}}
function stopAuto(){{running=false}}
function changeSpeed(){{var sp=[4000,6000,10000,15000];var lb=["4s","6s","10s","15s"];var cl=document.getElementById("delayDisplay").textContent;var i=lb.indexOf(cl);i=(i+1)%sp.length;delay=sp[i];document.getElementById("delayDisplay").textContent=lb[i];document.querySelector(".speed-btn").textContent="Speed: "+lb[i]}}
function processNext(){{if(!running||current>=total)return;var btn=document.querySelector("#p"+current+" .btn.pdf");if(btn){{var w=window.open(btn.href,"_blank");markOpened(current);if(w)setTimeout(function(){{try{{w.close()}}catch(e){{}}}},25000)}}current++;document.getElementById("prog").value=current;if(running&&current<total)setTimeout(processNext,delay)}}
function markOpened(i){{var s=document.getElementById("s"+i);if(s){{s.textContent="opened";s.className="status opened"}}var p=document.getElementById("p"+i);if(p)p.style.opacity="0.5";opened++;document.getElementById("cnt").textContent=opened}}
document.addEventListener("keydown",function(e){{if(e.key==="s"||e.key==="S")startAuto();if(e.key==="x"||e.key==="X")stopAuto()}});
console.log("Ready! Press S to start auto-download.");
</script></body></html>'''

        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(html.encode('utf-8')))
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    async def _get_papers(self):
        """Get paper list from RSS feeds."""
        import aiohttp
        from xml.etree import ElementTree as ET

        ALL_JOURNALS = [
            ('GJXW','国际新闻界','新闻传播学'),('YANJ','新闻与传播研究','新闻传播学'),
            ('XWDX','新闻大学','新闻传播学'),('DACB','当代传播','新闻传播学'),
            ('MSSB','模式识别与人工智能','人工智能'),('ZDHB','自动化学报','人工智能'),
            ('JFYZ','计算机研究与发展','人工智能'),('PZKX','中国科学：信息科学','人工智能'),
            ('RLXB','人类学学报','人类学'),('MZYJ','民族研究','人类学'),
            ('SHXJ','社会学研究','人类学'),('SHEH','社会','人类学'),
            ('JSJX','计算机学报','计算机科学'),('RJXB','软件学报','计算机科学'),
            ('HXXB','化学学报','化学'),('GDXH','高等学校化学学报','化学'),
            ('FXHX','分析化学','化学'),('YJHU','有机化学','化学'),
        ]

        H = {'User-Agent': 'Mozilla/5.0', 'Cookie': COOKIES_RAW}
        all_papers = []

        async with aiohttp.ClientSession(headers=H) as session:
            for code, name, disc in ALL_JOURNALS:
                try:
                    async with session.get(
                        f'https://rss.cnki.net/knavi/rss/{code}?pcode=CJFD,CCJD',
                        ssl=False, timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        root = ET.fromstring(await resp.text())

                    for item in root.findall('.//item')[:20]:
                        all_papers.append({
                            'title': (item.findtext('title', '') or '').strip(),
                            'link': (item.findtext('link', '') or '').strip(),
                            'author': (item.findtext('author', '') or '').strip(),
                            'journal_name': name,
                            'discipline': disc,
                        })
                except Exception as e:
                    print(f'  RSS error for {code}: {e}')
                await asyncio.sleep(0.2)

        return all_papers

    async def _proxy_request(self, target_url):
        """Proxy a CNKI request, injecting auto-click JS into HTML responses."""
        try:
            H = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Cookie': COOKIES_RAW,
            }

            async with aiohttp.ClientSession(headers=H) as session:
                async with session.get(target_url, ssl=False, allow_redirects=True,
                                      timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    body = await resp.read()
                    ct = resp.headers.get('Content-Type', 'text/html')

                    # Only inject JS into HTML responses
                    if 'text/html' in ct:
                        body_s = body.decode('utf-8', errors='replace')
                        # Inject auto-click JS before </body> or </head>
                        if '</body>' in body_s:
                            body_s = body_s.replace('</body>', HIGHLIGHT_CSS + AUTO_CLICK_JS + '</body>')
                        elif '</head>' in body_s:
                            body_s = body_s.replace('</head>', AUTO_CLICK_JS + '</head>')
                        else:
                            body_s = AUTO_CLICK_JS + body_s
                        body = body_s.encode('utf-8')
                        print(f'  Injected auto-click JS into {len(body_s)} chars HTML')

                    self.send_response(resp.status)
                    self.send_header('Content-Type', ct)
                    self.send_header('Content-Length', len(body))
                    self.end_headers()
                    self.wfile.write(body)

        except Exception as e:
            print(f'  Proxy error: {e}')
            self.send_response(502)
            self.end_headers()
            self.wfile.write(f'Proxy error: {e}'.encode())

    def log_message(self, format, *args):
        pass  # Silent


if __name__ == '__main__':
    print(f'=' * 60)
    print(f'CNKI Auto-Download Proxy Server')
    print(f'=' * 60)
    print(f'URL: http://localhost:{PORT}/')
    print(f'')
    print(f'This server proxies CNKI pages and injects auto-click JS.')
    print(f'Opening browser...')

    import webbrowser
    webbrowser.open(f'http://localhost:{PORT}/')

    print(f'Server running on port {PORT}...')
    print(f'Press Ctrl+C to stop.')

    server = http.server.HTTPServer(('127.0.0.1', PORT), ProxyHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nServer stopped.')
        server.shutdown()
