#!/usr/bin/env python3
"""Receive a CI source archive and release only the Kunteng application."""
from datetime import datetime, timezone
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import shutil
import subprocess
import sys
import tarfile
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT=Path('/opt/kunteng-truck')
MAX_ARCHIVE=128*1024*1024
MAX_EXPANDED=512*1024*1024


def validate_sha(value):
    if not re.fullmatch(r'[a-f0-9]{40}',value):
        raise ValueError('Expected a complete lowercase Git commit SHA')
    return value


def checked_members(package):
    members=package.getmembers()
    seen=set()
    size=0
    blocked={'.git','.env','.venv','data','work','private','staticfiles'}
    for member in members:
        path=PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] in blocked:
            raise ValueError('Archive contains an unsafe path')
        if not (member.isfile() or member.isdir()) or member.name in seen:
            raise ValueError('Archive links, devices and duplicate paths are not accepted')
        seen.add(member.name)
        size+=member.size
        if size>MAX_EXPANDED:
            raise ValueError('Expanded release exceeds the size limit')
    required={'manage.py','requirements.txt','config/settings.py','deploy/prepare_release.py'}
    if not required.issubset(seen):
        raise ValueError('Release is missing required application files')
    return members


def environment():
    values={}
    for line in (ROOT/'shared/app.env').read_text().splitlines():
        if not line or line.lstrip().startswith('#'):
            continue
        key,value=line.split('=',1)
        if not re.fullmatch(r'[A-Z][A-Z0-9_]*',key):
            raise ValueError('Invalid environment key')
        values[key]=value
    assert values.get('DEBUG')=='0'
    assert values.get('DATA_DIR')==str(ROOT/'shared/data')
    assert values.get('SITE_URL','').startswith('https://')
    assert len(values.get('SECRET_KEY',''))>=50
    return {**os.environ,**values,'PYTHONUNBUFFERED':'1','PYTHONDONTWRITEBYTECODE':'1','PIP_DISABLE_PIP_VERSION_CHECK':'1'}


def as_application(command,release,env):
    subprocess.run(['runuser','-u','kunteng-web','--',*map(str,command)],cwd=release,env=env,check=True)


def health(site_url):
    request=Request('http://127.0.0.1:18086/healthz/',headers={'Host':urlsplit(site_url).hostname,'X-Forwarded-Proto':'https'})
    with urlopen(request,timeout=5) as response:
        return response.status==200 and json.load(response)=={'status':'ok'}


def main():
    sha=validate_sha(sys.argv[1] if len(sys.argv)==2 else '')
    if os.geteuid()!=0:
        raise PermissionError('Release helper requires its configured sudo entrypoint')
    with (ROOT/'.deploy.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        archive=sys.stdin.buffer.read(MAX_ARCHIVE+1)
        if not archive or len(archive)>MAX_ARCHIVE:
            raise ValueError('Source archive is empty or exceeds the size limit')
        with tarfile.open(fileobj=io.BytesIO(archive),mode='r:gz') as package:
            members=checked_members(package)
            stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            release=ROOT/'releases'/f'{stamp}-{sha[:12]}'
            release.mkdir(mode=0o750)
            # Extract only plain files and directories into a newly created directory.
            for member in members:
                target=release/member.name
                if member.isdir():
                    target.mkdir(mode=0o750,parents=True,exist_ok=True)
                else:
                    target.parent.mkdir(mode=0o750,parents=True,exist_ok=True)
                    with package.extractfile(member) as source,target.open('xb') as output:
                        shutil.copyfileobj(source,output)
                    target.chmod(0o640)
        account=pwd.getpwnam('kunteng-web')
        for path in [release,*release.rglob('*')]:
            os.chown(path,account.pw_uid,account.pw_gid)
        env=environment()
        python=release/'.venv/bin/python'
        print('Installing isolated release dependencies...',flush=True)
        as_application([ROOT/'runtime/python/bin/python3','-m','venv',release/'.venv'],release,env)
        as_application([python,'-m','pip','install','--only-binary=:all:','--no-cache-dir','-r','requirements.txt'],release,env)
        subprocess.run(['/usr/bin/python3','/usr/local/lib/kunteng-backup.py'],check=True)
        as_application([python,'deploy/prepare_release.py'],release,env)
        current=ROOT/'current'
        previous=current.resolve() if current.is_symlink() else None
        if previous and not previous.is_relative_to(ROOT/'releases'):
            raise ValueError('Current release points outside this application')
        pending=ROOT/('.current-'+stamp)
        pending.symlink_to(release)
        os.replace(pending,current)
        try:
            subprocess.run(['systemctl','restart','kunteng-truck.service'],check=True)
            for attempt in range(25):
                try:
                    if health(env['SITE_URL']): break
                except Exception: pass
                time.sleep(2)
            else: raise RuntimeError('Application health check failed')
        except Exception:
            if previous:
                pending.symlink_to(previous)
                os.replace(pending,current)
                subprocess.run(['systemctl','restart','kunteng-truck.service'],check=True)
            else:
                subprocess.run(['systemctl','stop','kunteng-truck.service'],check=True)
            raise
        record={'commit':sha,'source_sha256':hashlib.sha256(archive).hexdigest(),'release':str(release),'previous':str(previous) if previous else None,'site_url':env['SITE_URL'],'released_at':datetime.now(timezone.utc).isoformat(),'health':'passed'}
        (ROOT/'current-release.json').write_text(json.dumps(record,indent=2)+'\n')
        print(json.dumps(record),flush=True)


if __name__=='__main__':
    main()
