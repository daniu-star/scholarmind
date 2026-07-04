"""Download CNKI paper via undetected Chrome."""
import undetected_chromedriver as uc
import time, os, asyncio, sys
import aiohttp
from xml.etree import ElementTree as ET


async def get_paper_link(cookies_raw):
    H = {'User-Agent': 'Mozilla/5.0', 'Cookie': cookies_raw}
    async with aiohttp.ClientSession(headers=H) as s:
        async with s.get('https://rss.cnki.net/knavi/rss/GJXW?pcode=CJFD,CCJD', ssl=False) as r:
            root = ET.fromstring(await r.text())
            item = root.findall('.//item')[0]
            return item.findtext('link', ''), item.findtext('title', '')


def main():
    raw = open('sessions/cnki_verified.json', 'r', encoding='utf-8').read().strip()
    paper_link, title = asyncio.run(get_paper_link(raw))
    print(f'Paper: {title[:60]}')
    print(f'Link: {paper_link[:100]}')

    os.makedirs('downloads', exist_ok=True)

    options = uc.ChromeOptions()
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--window-size=1920,1080')
    prefs = {
        'download.default_directory': os.path.abspath('downloads'),
        'download.prompt_for_download': False,
        'download.directory_upgrade': True,
        'plugins.always_open_pdf_externally': True,
    }
    options.add_experimental_option('prefs', prefs)

    driver = uc.Chrome(headless=False, use_subprocess=True, version_main=149, options=options)

    try:
        print('[1] Visiting kns.cnki.net...')
        driver.get('https://kns.cnki.net/')
        time.sleep(3)
        print(f'    OK: {driver.title[:60]}')

        print('[2] Injecting cookies...')
        for part in raw.split('; '):
            if '=' in part:
                k, v = part.split('=', 1)
                try:
                    driver.add_cookie({'name': k.strip(), 'value': v.strip(), 'path': '/'})
                except:
                    pass

        print('[3] Opening paper detail page...')
        driver.get(paper_link)
        time.sleep(6)
        print(f'    Title: {driver.title[:80]}')
        print(f'    URL: {driver.current_url[:120]}')
        driver.save_screenshot('paper_detail_full.png')

        all_links = driver.execute_script("""
            return Array.from(document.querySelectorAll('a')).map(a => ({
                text: (a.textContent || '').trim(),
                href: a.href || ''
            }));
        """)

        dl_keywords = ['PDF', 'CAJ', 'pdf', 'caj', 'download', '下载', '全文', '原版']
        dl_links = [l for l in all_links
                    if any(kw in l['text'] for kw in dl_keywords)
                    or any(kw in l['href'].lower() for kw in ['download', 'order', '.pdf', '.caj'])]

        print(f'[4] Download links: {len(dl_links)}')
        for l in dl_links:
            print(f'    [{l["text"][:40]}] -> {l["href"][:120]}')

        if dl_links:
            pdf = next((l for l in dl_links if 'PDF' in l['text']), dl_links[0])
            print(f'\n[5] Navigating to: {pdf["text"][:40]}')
            driver.get(pdf['href'])
            time.sleep(15)

            print(f'    URL: {driver.current_url[:150]}')
            driver.save_screenshot('after_download.png')

            time.sleep(3)
            files = os.listdir('downloads')
            pdfs = [f for f in files if f.endswith('.pdf') or f.endswith('.caj')]
            crs = [f for f in files if f.endswith('.crdownload')]
            print(f'[6] Files: {files}')
            if pdfs:
                for p in pdfs:
                    sz = os.path.getsize(f'downloads/{p}')
                    print(f'    >>> SUCCESS: {p} ({sz} bytes) <<<')
            elif crs:
                print(f'    Download in progress, waiting 20s...')
                time.sleep(20)
                files2 = os.listdir('downloads')
                pdfs2 = [f for f in files2 if f.endswith('.pdf') or f.endswith('.caj')]
                if pdfs2:
                    for p in pdfs2:
                        sz = os.path.getsize(f'downloads/{p}')
                        print(f'    >>> SUCCESS: {p} ({sz} bytes) <<<')
                else:
                    print(f'    Download incomplete: {files2}')
        else:
            print('    No download links found!')

    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()

    finally:
        driver.quit()
        time.sleep(1)
        files = os.listdir('downloads')
        print(f'\nFinal files in downloads/:')
        for f in files:
            sz = os.path.getsize(f'downloads/{f}')
            print(f'  {f}: {sz} bytes')


if __name__ == '__main__':
    main()
