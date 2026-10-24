#!/usr/bin/env python3
"""Conservative HTML-to-Markdown backup of public Develog articles.

No unofficial/private API, login cookies, or bypassing access controls.
Fails closed if page content cannot be identified reliably.
"""
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as html_to_md

BASE = 'https://develog.develrocket.com'
HANDLE = None  # Loaded from config.json when the sync starts
ROOT = Path(__file__).resolve().parents[1]
POSTS = ROOT / 'posts'
ARCHIVE = ROOT / 'archive'
ARCHIVE_AFTER_MISSES = 3
MANIFEST = ROOT / 'posts.json'
HEADERS = {'User-Agent': 'DevelogPersonalBackup/1.0 (+public-page-only; GitHub Actions)'}
TIMEOUT = 20


def load_handle():
    # An explicit account is required; never silently sync the template author's posts.
    config_path = ROOT / 'config.json'
    config = json.loads(config_path.read_text(encoding='utf8')) if config_path.exists() else {}
    if not isinstance(config, dict):
        raise ValueError('config.json must be a JSON object')
    value = os.getenv('DEVELOG_HANDLE') or config.get('develog_handle', '')
    if not isinstance(value, str):
        raise ValueError('develog_handle must be a string')
    handle = value.strip().lstrip('@')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', handle):
        raise ValueError('Set your Develog username in config.json (develog_handle) before running.')
    return handle


def get_html(url):
    response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    return response.text


def article_urls(profile_html):
    """Only public same-origin links under /@handle/<slug>."""
    soup = BeautifulSoup(profile_html, 'html.parser')
    results = set()
    for a in soup.select('a[href]'):
        u = urlparse(urljoin(BASE, a['href']))
        if u.scheme != 'https' or u.netloc != urlparse(BASE).netloc:
            continue
        path = unquote(u.path).rstrip('/')
        prefix = f'/@{HANDLE}/'
        if path.startswith(prefix) and len(path) > len(prefix):
            slug = path[len(prefix):]
            if '/' not in slug and slug not in {'followers', 'following', 'likes', 'about'}:
                results.add(BASE + quote(path, safe='/@-._~'))
    return sorted(results)


def get_title(soup):
    node = soup.find('h1')
    if node and node.get_text(' ', strip=True):
        return node.get_text(' ', strip=True)
    node = soup.select_one('meta[property="og:title"]')
    if node and node.get('content'):
        return node['content'].strip().removesuffix(' - Develog')
    raise ValueError('Article title missing')


def summarize_page_structure(soup):
    """Short, privacy-conscious debug info: tag names/classes only, not content."""
    overview = []
    for selector in ['main', 'article', '[role="main"]', 'h1', 'time', 'div[class*="content"]',
                     'div[class*="markdown"]', 'div[class*="viewer"]', 'section']:
        nodes = soup.select(selector)
        lengths = sorted((len(n.get_text(' ', strip=True)) for n in nodes), reverse=True)[:3]
        overview.append(f'{selector}:{len(nodes)} top_text_lengths={lengths}')
    return '; '.join(overview)


def get_body(soup):
    """Find a plausible article body; never export the whole document."""
    selectors = [
        '[data-testid="post-content"]', '[data-testid="article-content"]',
        '[itemprop="articleBody"]', '[class*="markdown-body"]', '[class*="MarkdownBody"]',
        '[class*="markdownViewer"]', '[class*="MarkdownViewer"]',
        '[class*="markdown-viewer"]', '[class*="post-content"]',
        '[class*="postContent"]', '[class*="article-content"]',
        '[class*="articleContent"]', '[class*="contentBody"]',
        '[class*="viewer"]', 'article .prose', 'main article .markdown-body',
        'article .markdown-body', 'main .prose', '.tiptap', '.ProseMirror',
    ]
    for selector in selectors:
        nodes = soup.select(selector)
        if not nodes:
            continue
        node = max(nodes, key=lambda n: len(n.get_text(' ', strip=True)))
        if len(node.get_text(' ', strip=True)) >= 20 or node.find(['img', 'pre']):
            return node
    # A real semantic article can be accepted only if it has meaningful paragraphs/code,
    # and does not contain common global navigation or comment forms.
    for selector in ('article', 'main article', 'main [role="article"]'):
        for node in soup.select(selector):
            if (len(node.get_text(' ', strip=True)) >= 70 and
                    len(node.select('p, pre, h2, h3, ul, ol, blockquote')) >= 2 and
                    not node.select('nav, form, footer')):
                return node
    raise ValueError('Recognized article body not found. DOM structure: ' + summarize_page_structure(soup))

def safe_title(text):
    """Unicode titles are preserved, but path separators are removed."""
    text = unicodedata.normalize('NFC', text).strip()
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip(' .')
    return text[:90].rstrip(' .') or '글'


def published_date(soup):
    """Use a *verified* machine-readable publication date, never sync date."""
    for selector, attr in [
        ('meta[property="article:published_time"]', 'content'),
        ('meta[name="datePublished"]', 'content'),
        ('meta[itemprop="datePublished"]', 'content'),
        ('time[datetime]', 'datetime'),
    ]:
        node = soup.select_one(selector)
        if node and node.get(attr):
            raw = node[attr].strip()
            try:
                day = datetime.fromisoformat(raw.replace('Z', '+00:00')).date()
                return day.isoformat(), raw
            except ValueError:
                pass
    raise ValueError('Publication date not found; refusing to invent an original date')


def choose_filename(title, date, url, occupied):
    base = f'{safe_title(title)}({date})'
    filename = f'{base}.md'
    if filename in occupied:
        digest = hashlib.sha256(url.encode('utf8')).hexdigest()[:8]
        filename = f'{base}-{digest}.md'
    return filename


def checked_path(folder, filename):
    if not isinstance(filename, str) or filename in {'', '.', '..'} or Path(filename).name != filename or not filename.endswith('.md'):
        raise ValueError('Unsafe filename in manifest')
    return folder / filename


def normalized_manifest(manifest):
    result = {}
    for url, data in manifest.items():
        if not isinstance(url, str):
            raise ValueError('Invalid manifest URL')
        if isinstance(data, str):
            result[url] = {'file': data, 'status': 'active', 'missing_count': 0}
        elif isinstance(data, dict):
            item = dict(data)
            checked_path(POSTS, item.get('file'))
            if item.get('status', 'active') not in ('active', 'archived'):
                raise ValueError('Invalid manifest status')
            item.setdefault('status', 'active')
            item.setdefault('missing_count', 0)
            result[url] = item
        else:
            raise ValueError('Invalid manifest entry')
    return result

def normalize_image_urls(node, url):
    for img in node.select('img'):
        if not img.get('src') and img.get('data-src'):
            img['src'] = img['data-src']
        if img.get('src'):
            img['src'] = urljoin(url, img['src'])
    for a in node.select('a[href]'):
        a['href'] = urljoin(url, a['href'])


def strip_site_chrome(markdown):
    """Remove only recognizable *trailing* Develog UI, preserving the real post.

    Do not globally remove words like '공유' or '댓글': authors may write them.
    The footer signature must be found close to the end of the converted body.
    """
    lines = markdown.splitlines()
    if not lines:
        return markdown
    nonempty = [(i, line.strip()) for i, line in enumerate(lines) if line.strip()]
    # Exact author-profile link followed by notification/follow UI is a strong
    # footer signature; remove all UI from the preceding standalone Share item.
    owner_pattern = re.compile(r'^\[[^\]\n]+\]\(https://develog\.develrocket\.com/@[^/)\s]+/?\)$')
    owner_indices = [i for i, line in nonempty if owner_pattern.fullmatch(line)]
    notification = '새 글이 올라오면 Develog 알림으로 알려드려요'
    candidates = []
    for i in owner_indices:
        following = [v for k, v in nonempty if i < k <= i + 14]
        if any(notification in v for v in following) and any(v == '팔로우' for v in following):
            candidates.append(i)
    cut = None
    if candidates:
        i = candidates[-1]
        # The author box must be close to the end, not an example in the article.
        if len([1 for k, _ in nonempty if k > i]) <= 12:
            cut = i
            prev = [(k, v) for k, v in nonempty if k < i]
            if prev and prev[-1][1] in ('공유', 'Share'):
                cut = prev[-1][0]
    # Alternate footer: Share plus a comment counter near end of the article.
    if cut is None:
        comment_pattern = re.compile(r'^#{1,6}\s*댓글\s*\d+\s*$')
        comments = [i for i, v in nonempty if comment_pattern.fullmatch(v)]
        for i in reversed(comments):
            suffix = [v for k, v in nonempty if k >= i]
            if len(suffix) <= 4:
                prev = [(k, v) for k, v in nonempty if k < i]
                if prev and prev[-1][1] in ('공유', 'Share'):
                    cut = prev[-1][0]
                    break
    if cut is not None:
        return '\n'.join(lines[:cut]).rstrip()
    return markdown


def md_quote(value):
    return json.dumps(value, ensure_ascii=False)


def article_markdown(url, html):
    soup = BeautifulSoup(html, 'html.parser')
    title = get_title(soup)
    body = get_body(soup)
    normalize_image_urls(body, url)
    md = strip_site_chrome(html_to_md(str(body), heading_style='ATX', bullets='-', code_language='').strip())
    if len(md) < 10:
        raise ValueError('Extracted Markdown too short; refusing potentially incomplete backup')
    date, published = published_date(soup)
    source_header = ('---\n' + f'title: {md_quote(title)}\n' +
                     f'source: {md_quote(url)}\n' +
                     f'author: {md_quote(HANDLE)}\n' +
                     (f'published: {md_quote(published)}\n' if published else '') +
                     '---\n\n')
    return source_header + md + '\n', title, date


def main():
    global HANDLE
    HANDLE = load_handle()
    POSTS.mkdir(parents=True, exist_ok=True)
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    raw_manifest = json.loads(MANIFEST.read_text(encoding='utf8')) if MANIFEST.exists() else {}
    if not isinstance(raw_manifest, dict):
        raise ValueError('posts.json is not a JSON object')
    manifest = normalized_manifest(raw_manifest)
    # Prevent mixing backups from different accounts in one repository.
    for saved_url in manifest:
        if unquote(urlparse(saved_url).path).split('/')[1:2] != [f'@{HANDLE}']:
            raise ValueError('posts.json contains another account. Use a fresh repository for a new handle.')
    profile_url = f'{BASE}/@{quote(HANDLE)}'
    urls = article_urls(get_html(profile_url))
    print(f'Profile: {profile_url}; found {len(urls)} linked posts; manifest entries: {len(manifest)}')
    if not urls:
        print('Zero links: archiving disabled for safety; an empty response may be a loading failure.')
        return

    failures = []
    updated = {url: dict(item) for url, item in manifest.items()}
    occupied = {item['file'] for item in updated.values()}
    for url in urls:
        try:
            source, title, date = article_markdown(url, get_html(url))
            if url in updated:
                entry = updated[url]
                filename = entry['file']  # established title/date never change
            else:
                filename = choose_filename(title, date, url, occupied)
                entry = {'file': filename}
                occupied.add(filename)
            target = checked_path(POSTS, filename)
            if entry.get('status') == 'archived':
                archived = checked_path(ARCHIVE, filename)
                if archived.exists():
                    archived.replace(target)
                    print(f'Restored {filename}')
            old = target.read_text(encoding='utf8') if target.exists() else None
            if old != source:
                target.write_text(source, encoding='utf8')
                print(f'Updated {target.relative_to(ROOT)}')
            entry.update(status='active', missing_count=0)
            updated[url] = entry
        except (requests.RequestException, ValueError, OSError) as exc:
            failures.append(f'{url}: {exc}')
        time.sleep(0.5)

    # A partially failed scrape cannot be treated as an authoritative deletion snapshot.
    if not failures:
        for url, entry in updated.items():
            if url in urls or entry.get('status') != 'active':
                continue
            entry['missing_count'] = int(entry.get('missing_count', 0)) + 1
            if entry['missing_count'] >= ARCHIVE_AFTER_MISSES:
                src = checked_path(POSTS, entry['file'])
                dst = checked_path(ARCHIVE, entry['file'])
                if not src.exists():
                    failures.append(f'{url}: active post file missing: {src}')
                    continue
                if dst.exists():
                    failures.append(f'{url}: archive filename collision: {dst}')
                    continue
                src.replace(dst)
                entry['status'] = 'archived'
                print(f'Archived {entry["file"]} after {ARCHIVE_AFTER_MISSES} missing scans')
            else:
                print(f'Not seen {entry["file"]}: {entry["missing_count"]}/{ARCHIVE_AFTER_MISSES} successful scans; not yet archived')

    if updated != manifest or raw_manifest != updated:
        MANIFEST.write_text(json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf8')
    if failures:
        for failure in failures:
            print(f'ERROR: {failure}', file=sys.stderr)
        raise RuntimeError(f'{len(failures)} post(s) could not be backed up safely')


if __name__ == '__main__':
    main()
