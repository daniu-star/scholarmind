"""Complete CNKI PDF download flow with proper Referer handling."""
import asyncio, re, sys, os
import aiohttp
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

async def main():
    raw = open('sessions/cnki_verified.json', 'r', encoding='utf-8').read().strip()

    H = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Cookie': raw,
    }

    os.makedirs('downloads', exist_ok=True)

    async with aiohttp.ClientSession(headers=H) as session:
        # Get paper detail page
        print('[1] Getting paper...')
        async with session.get(
            'https://rss.cnki.net/knavi/rss/GJXW?pcode=CJFD,CCJD', ssl=False
        ) as resp:
            root = ET.fromstring(await resp.text())
            paper_link = root.findall('.//item')[0].findtext('link', '')

        async with session.get(paper_link, ssl=False, allow_redirects=True) as resp:
            detail_html = await resp.text()
            detail_url = str(resp.url)

        title = root.findall('.//item')[0].findtext('title', 'unknown')[:40]
        print(f'  Paper: {title}')
        print(f'  Detail: {detail_url[:80]}')

        # Extract download order ID
        dl_match = re.search(
            r'bar\.cnki\.net/bar/download/order\?id=([^"\'&\s]+)', detail_html
        )
        if not dl_match:
            print('  No download URL found!')
            return False

        order_id = dl_match.group(1)
        print(f'  Order ID: {order_id[:60]}...')

        # ── Follow the download chain ──
        # The chain is: bar.cnki.net -> login.cnki.net -> x.cnki.net -> PDF
        print('\n[2] Download order page...')
        async with session.get(
            f'https://bar.cnki.net/bar/download/order?id={order_id}',
            headers={**H, 'Referer': detail_url},
            ssl=False, allow_redirects=False
        ) as resp:
            loc = resp.headers.get('Location', '')
            print(f'  Status: {resp.status}')
            print(f'  Location: {unquote(loc)[:200]}')

            if not loc:
                print('  No redirect!')
                return False

            # Fix the malformed URL: bar.cnki.net//login.cnki.net/... -> login.cnki.net/...
            if 'login.cnki.net' in loc:
                parsed = urlparse(loc)
                path = parsed.path
                if path.startswith('/login.cnki.net'):
                    path = path[len('/login.cnki.net'):]
                login_url = f'https://login.cnki.net{path}?{parsed.query}'
            elif loc.startswith('http'):
                login_url = loc
            else:
                login_url = f'https://login.cnki.net{loc}'

            print(f'  Fixed URL: {login_url[:150]}')

        # Step 3: Visit login.cnki.net
        print('\n[3] Login page (with institutional cookies)...')
        async with session.get(
            login_url,
            headers={**H, 'Referer': f'https://bar.cnki.net/bar/download/order?id={order_id}'},
            ssl=False, allow_redirects=False
        ) as resp:
            loc = resp.headers.get('Location', '')
            set_cookie = resp.headers.get('Set-Cookie', '')
            print(f'  Status: {resp.status}')
            print(f'  Set-Cookie: {set_cookie[:150]}')

            if loc:
                print(f'  Location: {unquote(loc)[:200]}')
                if not loc.startswith('http'):
                    loc = f'https://login.cnki.net{loc}'

                # Step 4: Follow the redirect from login
                print('\n[4] Following post-login redirect...')
                async with session.get(
                    loc,
                    headers={**H, 'Referer': login_url},
                    ssl=False, allow_redirects=False
                ) as resp2:
                    loc2 = resp2.headers.get('Location', '')
                    body2 = await resp2.read()
                    print(f'  Status: {resp2.status} | Body: {len(body2)}B')

                    if body2[:4] == b'%PDF':
                        filepath = 'downloads/paper.pdf'
                        with open(filepath, 'wb') as f:
                            f.write(body2)
                        print(f'  >>> PDF DOWNLOADED! {len(body2)} bytes -> {filepath}')
                        return True

                    if loc2:
                        print(f'  Location: {unquote(loc2)[:200]}')
                        if not loc2.startswith('http'):
                            parsed = urlparse(str(resp2.url))
                            loc2 = f'{parsed.scheme}://{parsed.netloc}{loc2}'

                        # Step 5: Final redirect (should be auth-check or PDF)
                        print('\n[5] Final hop...')
                        async with session.get(
                            loc2,
                            headers={**H, 'Referer': str(resp2.url)},
                            ssl=False, allow_redirects=True
                        ) as resp3:
                            body3 = await resp3.read()
                            ct = resp3.headers.get('Content-Type', '')
                            cd = resp3.headers.get('Content-Disposition', '')
                            print(f'  Status: {resp3.status} | CT: {ct[:60]} | {len(body3)}B')
                            if cd:
                                print(f'  Content-Disposition: {cd[:100]}')

                            if body3[:4] == b'%PDF':
                                filepath = 'downloads/paper.pdf'
                                with open(filepath, 'wb') as f:
                                    f.write(body3)
                                print(f'  >>> PDF DOWNLOADED! {len(body3)} bytes -> {filepath}')
                                return True

                            # Check for redirect chain in HTML (JS redirect)
                            body3_s = body3.decode('utf-8', errors='replace')
                            js_redirect = re.search(
                                r'(?:location\.href|location\.replace)\s*=\s*["\']([^"\']+)["\']',
                                body3_s
                            )
                            if js_redirect:
                                js_url = js_redirect.group(1)
                                if not js_url.startswith('http'):
                                    parsed = urlparse(str(resp3.url))
                                    js_url = f'{parsed.scheme}://{parsed.netloc}{js_url}'
                                print(f'  -> JS redirect: {js_url[:150]}')

                                async with session.get(
                                    js_url,
                                    headers={**H, 'Referer': str(resp3.url)},
                                    ssl=False, allow_redirects=True
                                ) as resp4:
                                    body4 = await resp4.read()
                                    print(f'  Final: {resp4.status} | {len(body4)}B')
                                    if body4[:4] == b'%PDF':
                                        filepath = 'downloads/paper.pdf'
                                        with open(filepath, 'wb') as f:
                                            f.write(body4)
                                        print(f'  >>> PDF! {len(body4)} bytes -> {filepath}')
                                        return True

                            if len(body3) < 300:
                                print(f'  Body: {body3_s}')
                            else:
                                print(f'  Body preview: {body3_s[:400]}')
                    else:
                        if len(body2) < 500:
                            print(f'  Body: {body2.decode("utf-8", errors="replace")[:500]}')
            else:
                body = await resp.read()
                if len(body) < 500:
                    print(f'  Body: {body.decode("utf-8", errors="replace")[:500]}')

    return False


if __name__ == '__main__':
    success = asyncio.run(main())
    print(f'\n{"="*50}')
    print(f'Download {"SUCCESS" if success else "FAILED"}')
