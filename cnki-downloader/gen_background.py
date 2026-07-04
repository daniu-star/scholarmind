"""Generate background.js with embedded CNKI cookies."""
import json

raw = open('sessions/cnki_verified.json', 'r', encoding='utf-8').read().strip()

cookies_list = []
for part in raw.split('; '):
    if '=' in part:
        k, v = part.split('=', 1)
        k, v = k.strip(), v.strip()
        if k and v:
            cookies_list.append({'name': k, 'value': v})

js = '''// CNKI Cookie Injector + Auto Download Background Script
const CNKI_COOKIES = ''' + json.dumps(cookies_list, ensure_ascii=False) + ''';

const CNKI_DOMAINS = [
    '.cnki.net', 'www.cnki.net', 'kns.cnki.net', 'navi.cnki.net',
    'bar.cnki.net', 'login.cnki.net', 'rss.cnki.net', 'x.cnki.net',
    'gateway.cnki.net'
];

async function injectCookies() {
    let count = 0;
    for (const domain of CNKI_DOMAINS) {
        for (const cookie of CNKI_COOKIES) {
            try {
                const url = 'https://' + domain.replace(/^\./, '') + '/';
                await chrome.cookies.set({
                    url: url,
                    domain: domain,
                    name: cookie.name,
                    value: cookie.value,
                    path: '/',
                    secure: true,
                    sameSite: 'lax'
                });
                count++;
            } catch (e) {
                // Skip errors - cookie may exist or domain invalid
            }
        }
    }
    console.log('[CNKI AutoDL] Cookies injected: ' + count);
}

// Run on install, startup, and immediately
chrome.runtime.onInstalled.addListener(injectCookies);
chrome.runtime.onStartup.addListener(injectCookies);
injectCookies();
'''

with open('extension/background.js', 'w', encoding='utf-8') as f:
    f.write(js)

print(f'Generated background.js with {len(cookies_list)} cookies')
