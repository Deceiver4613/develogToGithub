import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import sync_develog
from sync_develog import article_urls, article_markdown, choose_filename, normalized_manifest, strip_site_chrome, load_handle
from unittest.mock import patch
import tempfile
import json


class SyncTests(unittest.TestCase):
    def setUp(self):
        sync_develog.HANDLE = 'fixtureuser'  # Test fixture only, not a distribution default.

    def test_missing_configuration_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(sync_develog, 'ROOT', Path(tmp)), patch.dict('os.environ', {}, clear=True):
                self.assertRaises(ValueError, load_handle)

    def test_account_loaded_from_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'config.json').write_text(json.dumps({'develog_handle': 'other_user'}))
            with patch.object(sync_develog, 'ROOT', Path(tmp)), patch.dict('os.environ', {}, clear=True):
                self.assertEqual(load_handle(), 'other_user')

    def test_urls_only_owner(self):
        html = '<a href="/@fixtureuser/hello-world">A</a><a href="/@other/another">B</a><a href="https://evil.test/@fixtureuser/attack">C</a>'
        self.assertEqual(article_urls(html), ['https://develog.develrocket.com/@fixtureuser/hello-world'])

    def test_extract_markdown(self):
        html = '<html><meta property="article:published_time" content="2026-10-24T09:30:00+09:00"><h1>테스트 글</h1><article><div class="prose"><h2>소제목</h2><p>안녕하세요. 테스트 내용을 작성합니다.</p><pre><code>print(1)</code></pre></div></article></html>'
        text, title, date = article_markdown('https://develog.develrocket.com/@fixtureuser/test', html)
        self.assertEqual(title, '테스트 글')
        self.assertEqual(date, '2026-10-24')
        self.assertIn('## 소제목', text)
        self.assertIn('안녕하세요.', text)

    def test_article_body_semantic_fallback(self):
        html = '<meta property="article:published_time" content="2026-10-24T09:00:00+09:00"><h1>제목</h1><article><h2>본문 제목</h2><p>이것은 게시글 본문 첫번째 문장입니다. 게시글의 실제 본문을 보존해야 합니다.</p><p>두번째 문단에는 추가적인 설명과 예시가 충분히 포함되어 있습니다. 테스트입니다.</p></article>'
        text, _, _ = article_markdown('https://develog.develrocket.com/@fixtureuser/test', html)
        self.assertIn('두번째 문단', text)

    def test_filename(self):
        self.assertEqual(choose_filename('C# 배열', '2026-10-24', 'https://example.com/a', set()), 'C# 배열(2026-10-24).md')
        other = choose_filename('C# 배열', '2026-10-24', 'https://example.com/b', {'C# 배열(2026-10-24).md'})
        self.assertTrue(other.startswith('C# 배열(2026-10-24)-'))

    def test_legacy_manifest(self):
        self.assertEqual(normalized_manifest({'https://example.com/a': 'old.md'})['https://example.com/a']['file'], 'old.md')

    def test_requires_publication_date(self):
        with self.assertRaises(ValueError):
            article_markdown('https://develog.develrocket.com/@fixtureuser/test', '<h1>제목</h1><article><div class="prose"><p>충분한 길이의 게시글 본문 텍스트입니다.</p></div></article>')

    def test_strip_site_footer(self):
        md = """## 본문

실제 코드와 설명은 남아야 합니다.

공유

[예시작성자](https://develog.develrocket.com/@fixtureuser)

새 글이 올라오면 Develog 알림으로 알려드려요

팔로우

## 댓글 0"""
        got = strip_site_chrome(md)
        self.assertEqual(got, '## 본문\n\n실제 코드와 설명은 남아야 합니다.')

    def test_do_not_remove_article_about_sharing(self):
        md = "## 공유\n\n공유를 주제로 한 글입니다.\n\n## 댓글 0"
        self.assertEqual(strip_site_chrome(md), md)

    def test_footer_in_article_extraction(self):
        html =             '<meta property="article:published_time" content="2026-10-24T09:00:00+09:00"><h1>제목</h1>' \
            '<article><div class="prose"><h2>본문</h2><p>내용을 보존해야 합니다.</p>' \
            '<p>공유</p><p><a href="https://develog.develrocket.com/@fixtureuser">예시작성자</a></p>' \
            '<p>새 글이 올라오면 Develog 알림으로 알려드려요</p><p>팔로우</p><h2>댓글 0</h2></div></article>'
        text, _, _ = article_markdown('https://develog.develrocket.com/@fixtureuser/test', html)
        self.assertIn('내용을 보존해야 합니다', text)
        self.assertNotIn('팔로우', text)
        self.assertNotIn('댓글 0', text)

    def test_fail_closed(self):
        with self.assertRaises(ValueError):
            article_markdown('https://develog.develrocket.com/@fixtureuser/test', '<h1>글</h1><nav>메뉴</nav>')

if __name__ == '__main__':
    unittest.main()
