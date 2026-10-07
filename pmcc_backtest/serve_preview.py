"""Loopback-only static preview under the real GitHub Pages project prefix."""
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT=Path(__file__).resolve().parents[1]
PREFIX='/535_fintech/'


class Preview(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs): super().__init__(*args,directory=str(ROOT),**kwargs)
    def do_GET(self):
        path=unquote(urlsplit(self.path).path)
        if not path.startswith(PREFIX):
            self.send_error(404,'Use /535_fintech/');return
        relative=path[len(PREFIX):]
        if any(part.startswith('.') or part in ('local_data','pmcc_backtest') for part in Path(relative).parts):
            self.send_error(403,'Private/source directory is not served');return
        self.path='/'+relative
        super().do_GET()
    def list_directory(self,path):
        self.send_error(403,'Directory listing disabled');return None


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=int,default=8768)
    args=p.parse_args();print(f'http://127.0.0.1:{args.port}{PREFIX}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Preview).serve_forever()
