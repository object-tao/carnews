#!/usr/bin/env python3
"""Private, consistent SQLite and media backup for this application only."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tarfile
from tempfile import TemporaryDirectory

ROOT=Path('/opt/kunteng-truck')


def main():
    os.umask(0o077)
    backups=ROOT/'backups'
    backups.mkdir(mode=0o700,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination=backups/f'kunteng-{stamp}.tar.gz'
    partial=destination.with_suffix('.partial')
    database=ROOT/'shared/data/db.sqlite3'
    with TemporaryDirectory(prefix='.snapshot-',dir=backups) as scratch:
        snapshot=Path(scratch)/'db.sqlite3'
        if database.exists():
            with sqlite3.connect(f'file:{database}?mode=ro',uri=True) as source,sqlite3.connect(snapshot) as target:
                source.backup(target)
                assert target.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        try:
            with tarfile.open(partial,'w:gz') as package:
                if snapshot.exists(): package.add(snapshot,arcname='data/db.sqlite3')
                media=ROOT/'shared/data/media'
                if media.exists(): package.add(media,arcname='data/media')
                cgr=ROOT/'shared/data/cgr'
                if cgr.exists(): package.add(cgr,arcname='data/cgr')
                for filename in ('shared/app.env','current-release.json'):
                    path=ROOT/filename
                    if path.exists(): package.add(path,arcname=filename)
            with tarfile.open(partial,'r:gz') as package:
                for member in package.getmembers():
                    if member.isfile():
                        with package.extractfile(member) as source:
                            while source.read(1024*1024): pass
            os.replace(partial,destination)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
    digest=hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(destination.suffix+'.sha256').write_text(digest+'  '+destination.name+'\n')
    print(json.dumps({'backup':str(destination),'bytes':destination.stat().st_size,'sha256':digest}),flush=True)


if __name__=='__main__': main()
