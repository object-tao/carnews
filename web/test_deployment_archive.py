import importlib.util
import io
import tarfile
from unittest import TestCase

from django.conf import settings


class DeploymentArchiveTests(TestCase):
    @classmethod
    def setUpClass(cls):
        import sys
        from unittest.mock import MagicMock,patch
        spec=importlib.util.spec_from_file_location('native_release',settings.BASE_DIR/'deploy/native_release.py')
        cls.release=importlib.util.module_from_spec(spec)
        try:
            import fcntl
            import pwd
            spec.loader.exec_module(cls.release)
        except ModuleNotFoundError:
            with patch.dict(sys.modules,{'fcntl':MagicMock(),'pwd':MagicMock()}):
                spec.loader.exec_module(cls.release)

    def archive(self,extra=None):
        data=io.BytesIO()
        with tarfile.open(fileobj=data,mode='w:gz') as package:
            for name in ['manage.py','requirements.txt','config/settings.py','deploy/prepare_release.py']:
                item=tarfile.TarInfo(name)
                item.size=1
                package.addfile(item,io.BytesIO(b'x'))
            if extra is not None: package.addfile(extra)
        data.seek(0)
        return tarfile.open(fileobj=data,mode='r:gz')

    def test_valid_release_and_strict_commit_identifier(self):
        self.assertEqual(self.release.validate_sha('a'*40),'a'*40)
        for value in ['main','a'*39,'a'*40+';id','A'*40,'../other']:
            with self.subTest(value=value),self.assertRaises(ValueError):
                self.release.validate_sha(value)
        with self.archive() as package:
            self.assertEqual(len(self.release.checked_members(package)),4)

    def test_archive_rejects_escape_and_private_data(self):
        for name in ['../outside','/etc/passwd','data/db.sqlite3','.env','work/private.json','.git/config']:
            with self.subTest(name=name),self.archive(tarfile.TarInfo(name)) as package,self.assertRaises(ValueError):
                self.release.checked_members(package)

    def test_archive_rejects_links_and_duplicate_files(self):
        for kind in [tarfile.SYMTYPE,tarfile.LNKTYPE,tarfile.FIFOTYPE]:
            entry=tarfile.TarInfo('linked')
            entry.type=kind
            entry.linkname='/etc/passwd'
            with self.archive(entry) as package,self.assertRaises(ValueError):
                self.release.checked_members(package)
        with self.archive(tarfile.TarInfo('manage.py')) as package,self.assertRaises(ValueError):
            self.release.checked_members(package)

    def test_native_service_is_separate_and_loopback_only(self):
        service=(settings.BASE_DIR/'deploy/kunteng-truck.service').read_text()
        self.assertIn('User=kunteng-web',service)
        self.assertIn('--bind 127.0.0.1:18086',service)
        self.assertNotIn('/opt/imt',service)
        self.assertIn('ReadWritePaths=/opt/kunteng-truck/shared/data',service)
