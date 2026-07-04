"""Final CNKI PDF download attempt - multiple strategies."""
import asyncio, re, os
import aiohttp
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

async def try_download(session, url, headers, label):
    """Try to download from a URL, following all redirects."""
    print(f'\n[{label}] {url[:130]}')
    try:
        async with session.get(
            url, headers=headers, ssl=False, allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            body = await resp.read()
            ct = resp.headers.get('Content-Type', '')
            cd = resp.headers.get('Content-Disposition', '')
            final = str(resp.url)
            print(f'  Status: {resp.status} | CT: {ct[:50]} | {len(body)}B')
            print(f'  Final URL: {final[:150]}')
            if cd:
                print(f'  Content-Disposition: {cd[:100]}')

            if body[:4] == b'%PDF':
                filepath = f'downloads/{label}.pdf'
                with open(filepath, 'wb') as f:
                    f.write(body)
                print(f'  >>> PDF DOWNLOADED! {len(body)} bytes -> {filepath}')
                return True

            if len(body) < 500 and body[:4] != b'%PDF':
                print(f'  Body: {body.decode("utf-8", errors="replace")[:300]}')
            elif len(body) > 100:
                body_s = body.decode('utf-8', errors='replace')
                if 'error' in body_s.lower() or 'Error' in body_s or 'wrong' in body_s.lower():
                    print(f'  Error page: {body_s[:300]}')
                else:
                    print(f'  HTML: {len(body)} chars | {body_s[:300]}')
    except Exception as e:
        print(f'  Error: {str(e)[:120]}')
    return False


async def main():
    raw = open('sessions/cnki_verified.json', 'r', encoding='utf-8').read().strip()

    base_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Cookie': raw,
    }

    os.makedirs('downloads', exist_ok=True)

    async with aiohttp.ClientSession(headers=base_headers) as session:
        # Get paper detail
        async with session.get(
            'https://rss.cnki.net/knavi/rss/GJXW?pcode=CJFD,CCJD', ssl=False
        ) as resp:
            root = ET.fromstring(await resp.text())
            item = root.findall('.//item')[0]
            paper_link = item.findtext('link', '')
            title = item.findtext('title', 'unknown')

        print(f'Paper: {title[:60]}')

        async with session.get(paper_link, ssl=False, allow_redirects=True) as resp:
            detail_html = await resp.text()
            detail_url = str(resp.url)

        # Extract parameters
        fn_match = re.search(r'filename=([^&"\'\s]+)', detail_html)
        db_match = re.search(r'dbcode=([^&"\'\s]+)', detail_html)
        tb_match = re.search(r'tablename=([^&"\'\s]+)', detail_html)
        fs_match = re.search(r'filesourcetype=([^&"\'\s]+)', detail_html)
        filename = fn_match.group(1) if fn_match else ''
        dbcode = db_match.group(1) if db_match else 'CJFQ'
        tablename = tb_match.group(1) if tb_match else ''
        filetype = fs_match.group(1) if fs_match else '1'

        print(f'  Filename: {filename} | Dbcode: {dbcode} | Table: {tablename}')

        # Strategy 1: Auth-check URL with all params
        detail_headers = {**base_headers, 'Referer': detail_url}

        auth_url = (
            f'https://x.cnki.net/web/page/auth-check'
            f'?redirectsource=zkjbj&redirectjump=yxread'
            f'&filesourcetype={filetype}&dbcode={dbcode}'
            f'&tablename={tablename}&filename={filename}'
        )
        if await try_download(session, auth_url, detail_headers, 'AuthCheck'):
            return

        # Strategy 2: Bar download order with all proper Referers
        dl_match = re.search(
            r'bar\.cnki\.net/bar/download/order\?id=([^"\'&\s]+)', detail_html
        )
        if dl_match:
            order_id = dl_match.group(1)
            order_url = f'https://bar.cnki.net/bar/download/order?id={order_id}'

            # Follow with allow_redirects to see the full chain
            if await try_download(session, order_url, detail_headers, 'BarOrder'):
                return

        # Strategy 3: Direct gateway download
        gw_urls = [
            f'https://gateway.cnki.net/web/page/download?filename={filename}&dbcode={dbcode}',
            f'https://gateway.cnki.net/download/file?filename={filename}&dbcode={dbcode}',
        ]
        for i, gw_url in enumerate(gw_urls):
            if await try_download(session, gw_url, detail_headers, f'Gateway{i}'):
                return

        # Strategy 4: Old CNKI detail page with download flag
        old_urls = [
            f'https://kns.cnki.net/kcms/detail/detail.aspx?dbcode={dbcode}&filename={filename}&flag=download',
            f'https://kns.cnki.net/kcms/detail/detail.aspx?dbcode={dbcode}&filename={filename}&v=&type=download',
        ]
        for i, old_url in enumerate(old_urls):
            if await try_download(session, old_url, detail_headers, f'OldDetail{i}'):
                return

        # Strategy 5: Direct PDF from cnki.net
        pdf_urls = [
            f'https://kns.cnki.net/kcms2/article/abstract?v=&filename={filename}&type=download',
            f'https://kns.cnki.net/kcms/detail/frame/list.aspx?dbcode={dbcode}&filename={filename}&type=pdf',
        ]
        for i, pdf_url in enumerate(pdf_urls):
            if await try_download(session, pdf_url, detail_headers, f'DirectPDF{i}'):
                return

    print('\nAll strategies failed. PDF download requires browser JS execution.')


if __name__ == '__main__':
    asyncio.run(main())
