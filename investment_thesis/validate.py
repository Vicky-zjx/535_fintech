"""Read-only validation of the independent thesis page and its evidence."""
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import urlsplit, unquote
from final_project.data_provider import digest
from final_project.historical import analyze as historical_analysis
from final_project.validate_publication import equivalent_observations
from .research import analyze, csv_text
from .option_audit import audit as option_audit


class Document(HTMLParser):
    def __init__(self):
        super().__init__(); self.urls=[]; self.ids=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if a.get('id'): self.ids.append(a['id'])
        self.urls += [v for k,v in attrs if k in ('href','src') and v]


def check(root):
    root=Path(root); page=root/'investment-thesis'
    market=json.loads((root/'docs/data/market_snapshot.json').read_text())
    h=json.loads((root/'docs/data/historical_signals.json').read_text())
    d=json.loads((page/'data/thesis_tracker.json').read_text())
    if h['market_snapshot_sha256']!=digest(market):
        raise ValueError('Retained history and market snapshot disagree')
    if any(not equivalent_observations(h.get(k),v) for k,v in historical_analysis(market).items()):
        raise ValueError('Historical signals do not reproduce from real closes')
    expected=analyze(h)
    expected['option_audit']=option_audit(root)
    if any(not equivalent_observations(d.get(k),v) for k,v in expected.items()):
        raise ValueError('Thesis statistics do not reproduce from retained history')
    if (page/'data/thesis_observations.csv').read_text()!=csv_text(expected):
        raise ValueError('CSV differs from JSON path observations')
    history=json.loads((root/'course/proposal_history.json').read_text())
    for e in d['cost_budget']['examples']:
        if not any(p['order']['id']==f"fin535-course-{e['ticker'].lower()}-put-2026-11-17"
                   and p['order']['strike']==e['strike'] for p in history['proposals']):
            raise ValueError('Cost illustration strike differs from recorded proposal')
    html=(page/'index.html').read_text(); doc=Document();doc.feed(html)
    if '<html lang="en">' not in html or any('\u4e00'<=c<='\u9fff' for c in html):
        raise ValueError('English page required')
    if len(set(doc.ids))!=len(doc.ids):raise ValueError('Duplicate anchor')
    for link in doc.urls:
        u=urlsplit(link)
        if u.scheme or u.netloc:continue
        if not u.path:
            if u.fragment and u.fragment not in doc.ids:raise ValueError('Broken anchor: '+link)
            continue
        target=(page/unquote(u.path)).resolve()
        if not target.is_relative_to(root.resolve()) or not target.exists():
            raise ValueError('Missing/unsafe relative file: '+link)
        if u.fragment:
            target=target/'index.html' if target.is_dir() else target
            linked=Document();linked.feed(target.read_text())
            if u.fragment not in linked.ids:raise ValueError('Broken cross-page anchor: '+link)
    print('Independent thesis verified: real sources, reproducible statistics, CSV, English page and links. No orders written.')


if __name__=='__main__':check(Path(__file__).resolve().parents[1])
