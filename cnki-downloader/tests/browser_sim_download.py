"""Simulate exact browser download flow to get PDF."""
import asyncio, re, sys, os
import aiohttp
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

async def main():
    raw = open('sessions/cnki_verified.json', 'r', encoding='utf-8').read().strip()

    H = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Cookie': raw,
    }

    async with aiohttp.ClientSession() as session:
        # Get paper and download order URL
        async with session.get('https://rss.cnki.net/knavi/rss/GJXW?pcode=CJFD,CCJD',
                               ssl=False, headers=H) as resp:
            root = ET.fromstring(await resp.text())
            item = root.findall('.//item')[0]
            paper_url = item.findtext('link', '')
            title = item.findtext('title', '')

        async with session.get(paper_url, ssl=False, allow_redirects=True, headers=H) as resp:
            detail_html = await resp.text()

        dl_match = re.search(r'bar\.cnki\.net/bar/download/order\?id=([^"\'&\s]+)', detail_html)
        if not dl_match:
            print('No download URL found!')
            return
        order_id = dl_match.group(1)

        print(f'Paper: {title[:60]}')
        print(f'Order ID: {order_id[:60]}...')

        # ── Complete browser simulation ──
        browser_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Cache-Control': 'max-age=0',
            'Sec-Ch-Ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'cross-site',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
            'Cookie': raw,
            'Referer': paper_url,
        }

        order_url = f'https://bar.cnki.net/bar/download/order?id={order_id}'
        os.makedirs('downloads', exist_ok=True)

        # Step 1: bar.cnki.net
        print('\n[Hop 1] bar.cnki.net/bar/download/order')
        async with session.get(order_url, headers=browser_headers, ssl=False,
                               allow_redirects=False) as resp:
            loc = resp.headers.get('Location', '')
            sc = resp.headers.get('Set-Cookie', '')
            print(f'  Status: {resp.status}')
            if loc:
                print(f'  -> Location: {loc[:200]}')
            if sc:
                print(f'  -> Set-Cookie: {sc[:150]}')

            if resp.status not in (301, 302, 307, 308) or not loc:
                print('  No redirect - stopping')
                return

            # Fix URL
            if loc.startswith('//'):
                loc = 'https:' + loc
            elif not loc.startswith('http'):
                loc = f'https://login.cnki.net{loc}'

        # Step 2: login.cnki.net
        print(f'\n[Hop 2] login.cnki.net')
        async with session.get(loc, headers={**browser_headers, 'Referer': order_url,
                                              'Origin': 'https://bar.cnki.net'},
                               ssl=False, allow_redirects=False) as resp:
            loc2 = resp.headers.get('Location', '')
            sc2 = resp.headers.get('Set-Cookie', '')
            body2 = await resp.read()
            print(f'  Status: {resp.status} | Body: {len(body2)}B')

            if sc2:
                print(f'  -> Set-Cookie: {sc2[:150]}')

            # Check body for auto-redirect
            body2_s = body2.decode('utf-8', errors='replace')
            title_match = re.search(r'<title>([^<]+)</title>', body2_s)
            print(f'  Title: {title_match.group(1) if title_match else "N/A"}')

            # Find any redirect mechanism
            redirect_found = False

            # Meta refresh
            meta_url = re.search(r'<meta[^>]*url=([^"\'&\s]+)', body2_s, re.IGNORECASE)
            if meta_url and 'refresh' in body2_s[:500].lower():
                loc2 = meta_url.group(1).strip('"\'')
                print(f'  -> Meta-refresh: {loc2[:150]}')
                redirect_found = True

            # JS redirect
            if not redirect_found:
                for pattern in [r'location\.href\s*=\s*["\']([^"\']+)["\']',
                                r'location\.replace\s*\(\s*["\']([^"\']+)["\']\)',
                                r'self\.location\s*=\s*["\']([^"\']+)["\']']:
                    js_url = re.search(pattern, body2_s)
                    if js_url:
                        loc2 = js_url.group(1)
                        print(f'  -> JS redirect: {loc2[:150]}')
                        redirect_found = True
                        break

            # Form auto-submit
            if not redirect_found:
                form_match = re.search(r'<form[^>]*action=["\']([^"\']+)["\']', body2_s)
                if form_match:
                    action = form_match.group(1)
                    inputs = re.findall(r'<input[^>]*name=["\']([^"\']+)["\']\s+value=["\']([^"\']*)["\']', body2_s)
                    print(f'  -> Form: {action[:120]}')
                    print(f'     Inputs: {[(n,v[:30]) for n,v in inputs[:5]]}')

                    # Try form POST
                    if not action.startswith('http'):
                        action = f'https://login.cnki.net{action}' if action.startswith('/') else f'https://login.cnki.net/{action}'

                    post_data = {n: v for n, v in inputs if n}
                    async with session.post(action, data=post_data,
                                           headers={**browser_headers, 'Referer': str(resp.url),
                                                    'Content-Type': 'application/x-www-form-urlencoded'},
                                           ssl=False, allow_redirects=True) as post_resp:
                        post_body = await post_resp.read()
                        post_final = str(post_resp.url)
                        is_pdf = post_body[:4] == b'%PDF'
                        print(f'     -> POST result: {post_resp.status} | {len(post_body)}B | PDF={is_pdf}')
                        if is_pdf:
                            filepath = f'downloads/{title[:40]}.pdf'
                            filepath = re.sub(r'[<>:\"/\\\\|?*]', '_', filepath)
                            with open(filepath, 'wb') as f:
                                f.write(post_body)
                            print(f'     >>> PDF DOWNLOADED: {filepath} ({len(post_body)} bytes) <<<')
                            return
                    redirect_found = True

            if not redirect_found:
                print(f'  No redirect mechanism found on login page')

        # Step 3: Follow location to next hop
        if loc2:
            if loc2.startswith('//'):
                loc2 = 'https:' + loc2
            elif not loc2.startswith('http'):
                p = urlparse(str(resp.url))
                loc2 = f'{p.scheme}://{p.netloc}{loc2}'

            print(f'\n[Hop 3] Following: {loc2[:150]}')
            async with session.get(loc2, headers={**browser_headers, 'Referer': str(resp.url)},
                                   ssl=False, allow_redirects=True) as resp3:
                body3 = await resp3.read()
                ct3 = resp3.headers.get('Content-Type', '')
                cd3 = resp3.headers.get('Content-Disposition', '')
                final3 = str(resp3.url)
                is_pdf3 = body3[:4] == b'%PDF'

                print(f'  Status: {resp3.status} | CT: {ct3[:60]} | {len(body3)}B')
                print(f'  Final URL: {final3[:150]}')
                if cd3:
                    print(f'  CD: {cd3[:100]}')

                if is_pdf3:
                    filepath = f'downloads/{title[:40]}.pdf'
                    filepath = re.sub(r'[<>:\"/\\\\|?*]', '_', filepath)
                    with open(filepath, 'wb') as f:
                        f.write(body3)
                    print(f'  >>> PDF DOWNLOADED: {filepath} ({len(body3)} bytes) <<<')
                    return

                if len(body3) < 500:
                    body3_s = body3.decode('utf-8', errors='replace')
                    print(f'  Body: {body3_s}')
                    # Check for JS redirect in final page
                    js_final = re.search(r'location\.href\s*=\s*["\']([^"\']+)["\']', body3_s)
                    if js_final:
                        final_js_url = js_final.group(1)
                        print(f'  -> JS final redirect: {final_js_url[:150]}')
                        async with session.get(
                            final_js_url if final_js_url.startswith('http') else f'https://{urlparse(final3).netloc}{final_js_url}',
                            headers={**browser_headers, 'Referer': final3},
                            ssl=False, allow_redirects=True
                        ) as resp4:
                            body4 = await resp4.read()
                            is_pdf4 = body4[:4] == b'%PDF'
                            print(f'  -> Final: {resp4.status} | {len(body4)}B | PDF={is_pdf4}')
                            if is_pdf4:
                                filepath = f'downloads/{title[:40]}.pdf'
                                filepath = re.sub(r'[<>:\"/\\\\|?*]', '_', filepath)
                                with open(filepath, 'wb') as f:
                                    f.write(body4)
                                print(f'  >>> PDF DOWNLOADED: {filepath} <<<')
                                return

    print('\nDownload not completed - requires browser JavaScript execution')


if __name__ == '__main__':
    asyncio.run(main())
