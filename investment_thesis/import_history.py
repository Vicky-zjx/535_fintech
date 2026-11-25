"""Validate an external private download. Never copy raw data into the website."""
import argparse
import os
from pathlib import Path


def private_history_path(root):
    value = os.environ.get('THESIS_PRIVATE_HISTORY')
    if not value:
        return None
    path = Path(value).expanduser().resolve()
    if path.is_relative_to(Path(root).resolve()) or any((p/'.git').exists() for p in path.parents):
        raise ValueError('Raw historical evidence must remain outside Git and the served site')
    if not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError('Private historical evidence requires an existing 0600 file')
    return path


def import_download(source,root):
    from .download_history import load_download
    # This operation validates only; no implicit copy, import or overwrite.
    with_value = str(Path(source).resolve())
    old = os.environ.get('THESIS_PRIVATE_HISTORY')
    try:
        os.environ['THESIS_PRIVATE_HISTORY'] = with_value
        target = private_history_path(root)
    finally:
        if old is None: os.environ.pop('THESIS_PRIVATE_HISTORY', None)
        else: os.environ['THESIS_PRIVATE_HISTORY'] = old
    evidence=load_download(Path(source))
    from .reference import load
    if evidence['evidence']['metadata']['frozen_reference_sha256']!=load(root)['evidence_sha256']:
        raise ValueError('Download belongs to a different frozen reference')
    return target


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('artifact_json',type=Path);args=p.parse_args()
    print(import_download(args.artifact_json,Path(__file__).resolve().parents[1]))
