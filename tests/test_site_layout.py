"""Offline layout checks: protect existing routes while removing duplicate output."""
import ast
from html.parser import HTMLParser
from pathlib import Path
import unittest
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PAGES = ('index.html', 'options_surface_preview.html', 'covered-call/index.html',
         'covered-call/data.html', 'pmcc/index.html', 'wheel/index.html',
         'lseg-live/index.html', 'lseg-local/index.html')


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in ('href', 'src') and value:
                self.urls.append(value)


class SiteLayoutTests(unittest.TestCase):
    def test_existing_pages_have_no_broken_relative_file_links(self):
        for relative in PAGES:
            page = ROOT / relative
            links = Links()
            links.feed(page.read_text())
            for url in links.urls:
                parsed = urlsplit(url)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                with self.subTest(page=relative, link=url):
                    target = (page.parent / unquote(parsed.path)).resolve()
                    self.assertTrue(target.is_relative_to(ROOT))
                    self.assertTrue(target.exists(), f'{relative}: missing {url}')

    def test_preview_is_small_redirect_kept_in_sync_with_builder(self):
        preview = (ROOT / 'options_surface_preview.html').read_text()
        self.assertLess(len(preview), 1024)
        self.assertIn('http-equiv="refresh" content="0; url=./"', preview)
        tree = ast.parse((ROOT / 'build_preview.py').read_text())
        alias = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == 'PREVIEW_ALIAS' for t in node.targets))
        self.assertEqual(preview, ast.literal_eval(alias))

    def test_compact_page_uses_canonical_data_not_a_duplicate(self):
        self.assertFalse((ROOT / 'lseg-local/data.json').exists())
        self.assertTrue((ROOT / 'lseg-live/data.json').is_file())
        self.assertIn('href="../lseg-live/data.json"', (ROOT / 'lseg-local/index.html').read_text())
        workflow = (ROOT / '.github/workflows/lseg-plot.yml').read_text()
        self.assertNotIn('lseg-local/data.json', workflow)

    def test_keep_real_cache_and_required_templates(self):
        self.assertTrue((ROOT / 'option_pipeline_data.pkl').is_file())
        self.assertFalse((ROOT / 'option_pipeline_data.synthetic.pkl').exists())
        self.assertTrue((ROOT / 'wheel_backtest/page.html').is_file())
        self.assertTrue((ROOT / 'wheel/index.html').is_file())
        self.assertTrue((ROOT / 'covered-call/assets/plotly.min.js').is_file())


if __name__ == '__main__':
    unittest.main()
