"""Step-by-step trace of CNKI download redirect chain with proper Referer."""
import asyncio, re, sys
import aiohttp
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

async def main():
    raw = open('sessions/cnki_verified.json', 'r', encoding='utf-8').read().strip()

    base_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Cookie': raw,
    }

    async with aiohttp.ClientSession(headers=base_headers) as session:
        # Step 1: Get paper detail page (as Referer source)
        print('[Step 1] Getting RSS paper and detail page...')
        async with session.get('https://rss.cnki.net/knavi/rss/GJXW?pcode=CJFD,CCJD', ssl=False) as resp:
            root = ET.fromstring(await resp.text())
            paper_link = root.findall('.//item')[0].findtext('link', '')

        # Get the actual detail page URL (follow redirects)
        async with session.get(paper_link, ssl=False, allow_redirects=True) as resp:
            detail_html = await resp.text()
            detail_url = str(resp.url)

        print(f'  Detail URL: {detail_url[:100]}')

        # Extract download order ID
        dl_match = re.search(r'bar\.cnki\.net/bar/download/order\?id=([^"\'&\s]+)', detail_html)
        if not dl_match:
            print('  No download URL found')
            return

        order_id = dl_match.group(1)
        download_url = f'https://bar.cnki.net/bar/download/order?id={order_id}'

        # Also extract x.cnki.net auth-check URL
        auth_match = re.search(r'https://x\.cnki\.net/web/page/auth-check\?[^"\'\s]+', detail_html)
        auth_url = auth_match.group(0).replace('&amp;', '&') if auth_match else ''

        print(f'  Auth-check URL: {auth_url[:120]}...')

        # ── TRACE CHAIN WITH PROPER REFERER ──
        current_url = download_url
        referer = detail_url

        for hop in range(15):
            print(f'\n[Hop {hop}] {current_url[:130]}')

            hop_headers = {
                **base_headers,
                'Referer': referer,
                'Origin': 'https://kns.cnki.net',
            }

            try:
                async with session.get(
                    current_url, headers=hop_headers, ssl=False,
                    allow_redirects=False, timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    status = resp.status
                    location = resp.headers.get('Location', '')
                    ct = resp.headers.get('Content-Type', '')
                    cd = resp.headers.get('Content-Disposition', '')
                    body = await resp.read()

                    print(f'  Status: {status} | CT: {ct[:50]} | Size: {len(body)}B')
                    if cd:
                        print(f'  Content-Disposition: {cd[:100]}')

                    # Check if PDF!
                    if body[:4] == b'%PDF':
                        with open('downloads/downloaded_paper.pdf', 'wb') as f:
                            f.write(body)
                        print(f'  >>> PDF DOWNLOADED! {len(body)} bytes <<<')
                        print(f'  Saved: downloads/downloaded_paper.pdf')
                        return True

                    if body[:4] == b'%CAJ':
                        with open('downloads/downloaded_paper.caj', 'wb') as f:
                            f.write(body)
                        print(f'  >>> CAJ DOWNLOADED! {len(body)} bytes <<<')
                        return True

                    # Follow redirect
                    if location:
                        if not location.startswith('http'):
                            parsed = urlparse(str(resp.url))
                            location = f'{parsed.scheme}://{parsed.netloc}{location}'
                        print(f'  -> Location: {unquote(location)[:200]}')
                        current_url = location
                        referer = str(resp.url)
                        continue

                    # Check HTML body for redirect/form
                    body_s = body.decode('utf-8', errors='replace')

                    # Auto-submit form
                    form_action = re.search(r'<form[^>]*action="([^"]+)"[^>]*>', body_s)
                    form_inputs = re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', body_s)

                    if form_action and form_inputs:
                        action = form_action.group(1)
                        if not action.startswith('http'):
                            parsed = urlparse(str(resp.url))
                            action = f'{parsed.scheme}://{parsed.netloc}{action}'
                        print(f'  -> Form POST: {action[:120]}')

                        post_data = {n: v for n, v in form_inputs if n}
                        async with session.post(
                            action, data=post_data,
                            headers={**hop_headers, 'Referer': str(resp.url)},
                            ssl=False, allow_redirects=False
                        ) as post_resp:
                            post_body = await post_resp.read()
                            post_loc = post_resp.headers.get('Location', '')
                            post_ct = post_resp.headers.get('Content-Type', '')
                            print(f'     POST result: {post_resp.status} | {len(post_body)}B | CT: {post_ct[:50]}')

                            if post_body[:4] == b'%PDF':
                                with open('downloads/form_pdf.pdf', 'wb') as f:
                                    f.write(post_body)
                                print(f'     >>> PDF VIA FORM! {len(post_body)} bytes <<<')
                                return True

                            if post_loc:
                                if not post_loc.startswith('http'):
                                    parsed = urlparse(str(post_resp.url))
                                    post_loc = f'{parsed.scheme}://{parsed.netloc}{post_loc}'
                                current_url = post_loc
                                referer = str(post_resp.url)
                                break
                        continue

                    # JS redirect
                    js_loc = re.search(
                        r'(?:location\.href|location\.replace|window\.location)\s*=\s*["\']([^"\']+)["\']',
                        body_s
                    )
                    if js_loc:
                        new_url = js_loc.group(1)
                        if not new_url.startswith('http'):
                            parsed = urlparse(str(resp.url))
                            new_url = f'{parsed.scheme}://{parsed.netloc}{new_url}'
                        print(f'  -> JS redirect: {new_url[:150]}')
                        current_url = new_url
                        continue

                    # Show body and stop
                    if len(body_s) < 800:
                        print(f'  Body: {body_s}')
                    else:
                        print(f'  Body preview: {body_s[:500]}')
                    print(f'  (no more redirects)')
                    break

            except Exception as e:
                print(f'  Error: {str(e)[:150]}')
                break

    return False

if __name__ == '__main__':
    success = asyncio.run(main())
    print(f'\n{"="*50}')
    print(f'Download {"SUCCESS" if success else "FAILED"}')
