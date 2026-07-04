"""Start a local HTTP server with the download page and open browser."""
import http.server, os, sys, json, subprocess, threading, time, webbrowser

HOST = '127.0.0.1'
PORT = 8765
DOWNLOAD_DIR = os.path.abspath('downloads')

HTML_FILE = os.path.join(DOWNLOAD_DIR, 'all_papers_download.html')

if not os.path.exists(HTML_FILE):
    print(f'ERROR: {HTML_FILE} not found!')
    print('Run: python tests/generate_all_downloads.py first')
    sys.exit(1)

# Read the HTML and inject auto-start
html_content = open(HTML_FILE, 'r', encoding='utf-8').read()
# Add auto-start: begin downloading 3 seconds after page load
html_content = html_content.replace(
    '</body>',
    '<script>setTimeout(function(){ startAuto(); }, 3000);</script></body>'
)

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DOWNLOAD_DIR, **kwargs)

    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', len(html_content.encode('utf-8')))
            self.end_headers()
            self.wfile.write(html_content.encode('utf-8'))
        else:
            super().do_GET()

    def log_message(self, format, *args):
        pass  # Silent

# Start server
server = http.server.HTTPServer((HOST, PORT), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()

url = f'http://{HOST}:{PORT}/'
print(f'=' * 60)
print(f'CNKI Auto Download Server')
print(f'=' * 60)
print(f'Local server: {url}')
print(f'Serving: {HTML_FILE}')
print(f'Papers will download to: {DOWNLOAD_DIR}')
print(f'')
print(f'Opening browser now...')
print(f'The page will AUTO-START downloading in 3 seconds.')
print(f'Keep the browser window open and ALLOW POPUPS.')
print(f'')
print(f'Press Ctrl+C to stop the server.')

# Open in Chrome with specific flags
chrome_paths = [
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
]

chrome_exe = None
for p in chrome_paths:
    if os.path.exists(p):
        chrome_exe = p
        break

if chrome_exe:
    # Launch Chrome with: new window, maximized, allow popups
    subprocess.Popen([
        chrome_exe,
        '--new-window',
        '--start-maximized',
        url,
    ])
    print(f'Chrome launched: {chrome_exe}')
else:
    # Fallback: use default browser
    webbrowser.open(url)
    print('Default browser opened')

print(f'')
print(f'MONITORING: Check {DOWNLOAD_DIR} for downloaded PDFs')
print(f'Current files: {len(os.listdir(DOWNLOAD_DIR))}')

try:
    # Keep running and monitor for new PDFs
    last_count = len([f for f in os.listdir(DOWNLOAD_DIR) if f.endswith('.pdf') or f.endswith('.caj')])
    while True:
        time.sleep(10)
        current = len([f for f in os.listdir(DOWNLOAD_DIR) if f.endswith('.pdf') or f.endswith('.caj')])
        if current != last_count:
            print(f'  PDFs downloaded: {current}')
            last_count = current
except KeyboardInterrupt:
    print(f'\nServer stopped.')
    print(f'Total PDFs in {DOWNLOAD_DIR}: {last_count}')
    server.shutdown()
