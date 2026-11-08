import copy
import hashlib
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from web.models import Article, ResourceType
from web.port_images import apply_port_image_metadata


@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class PortSceneUpgradeTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.media = self.root / 'media'
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.ports, _ = ResourceType.objects.get_or_create(slug='ports', defaults={'name': '口岸介绍'})
        self.edition = json.loads((settings.BASE_DIR / 'content/ports/scene-upgrade-20261107.json').read_text(encoding='utf-8'))
        self.targets = {entry['id']: entry for entry in self.edition['entries']}

    def original_article(self, identifier, published=True):
        before = self.targets[identifier]['before']
        article = Article(
            slug='port-' + identifier, title='Administrator title', summary='Original summary',
            body='Administrator body', original_source='PRIVATE-ORIGINAL', kind='resources',
            category='口岸介绍', resource_type=self.ports, published=published,
            published_at=timezone.now() if published else None,
        )
        apply_port_image_metadata(article, before)
        article.save()
        article.image.save(identifier + '-original.png', ContentFile((settings.BASE_DIR / 'content/ports' / before['file']).read_bytes()))
        return article

    def upgrade(self, **options):
        call_command('upgrade_port_images', stdout=StringIO(), **options)

    def test_real_and_ai_images_replace_only_known_diagrams_and_keep_content(self):
        photo = self.original_article('0103')
        scene = self.original_article('0106')
        draft = self.original_article('0107', published=False)
        originals = [Path(item.image.path) for item in (photo, scene, draft)]
        self.upgrade()
        for item in (photo, scene, draft):
            item.refresh_from_db()
            self.assertEqual(item.body, 'Administrator body')
            self.assertEqual(item.title, 'Administrator title')
            self.assertEqual(item.original_source, 'PRIVATE-ORIGINAL')
            expected = self.targets[item.slug.removeprefix('port-')]['after']
            self.assertEqual(hashlib.sha256(Path(item.image.path).read_bytes()).hexdigest(), expected['sha256'])
        self.assertEqual(photo.image_taken_on, '2026-05-04')
        self.assertEqual(photo.image_license, 'CC BY 4.0')
        self.assertEqual(scene.image_taken_on, '')
        page = self.client.get(scene.get_absolute_url())
        self.assertContains(page, 'AI生成，非现场实拍')
        self.assertContains(page, 'photo-generated')
        self.assertNotContains(page, 'PRIVATE-ORIGINAL')
        self.assertFalse(draft.published)
        self.assertEqual(self.client.get('/article-images/port-0107/?size=card').status_code, 404)
        self.assertTrue(all(path.exists() for path in originals))
        files = sorted(self.media.rglob('*'))
        modified = scene.updated_at
        self.upgrade()
        scene.refresh_from_db()
        self.assertEqual(scene.updated_at, modified)
        self.assertEqual(files, sorted(self.media.rglob('*')))

    def test_administrator_metadata_or_image_changes_are_preserved(self):
        caption = self.original_article('0103')
        pixels = self.original_article('0106')
        caption.image_caption = 'Administrator replacement credit'
        caption.save()
        Path(pixels.image.path).write_bytes(b'Administrator replacement file')
        filenames = [caption.image.name, pixels.image.name]
        self.upgrade()
        caption.refresh_from_db()
        pixels.refresh_from_db()
        self.assertEqual(caption.image_caption, 'Administrator replacement credit')
        self.assertEqual([caption.image.name, pixels.image.name], filenames)
        self.assertEqual(Path(pixels.image.path).read_bytes(), b'Administrator replacement file')

    def test_dry_run_and_invalid_ai_disclosure_do_not_write(self):
        item = self.original_article('0106')
        original = item.image.name
        self.upgrade(dry_run=True)
        item.refresh_from_db()
        self.assertEqual(item.image.name, original)
        edition = copy.deepcopy(self.edition)
        target = next(entry for entry in edition['entries'] if entry['id'] == '0106')
        target['after']['note'] = 'Actual photograph'
        path = self.root / 'invalid.json'
        path.write_text(json.dumps(edition), encoding='utf-8')
        with self.assertRaises(CommandError):
            self.upgrade(edition=path)
        item.refresh_from_db()
        self.assertEqual(item.image.name, original)

    def test_storage_failure_restores_rows_and_retains_original_media(self):
        items = [self.original_article('0103'), self.original_article('0106')]
        originals = {item.pk: item.image.name for item in items}
        files = sorted(self.media.rglob('*'))
        real_save = FileSystemStorage._save
        count = 0

        def failing_save(storage, name, content):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('Simulated storage unavailable')
            return real_save(storage, name, content)

        with patch.object(FileSystemStorage, '_save', failing_save):
            with self.assertRaises(OSError):
                self.upgrade()
        for item in items:
            item.refresh_from_db()
            self.assertEqual(item.image.name, originals[item.pk])
        self.assertEqual(files, sorted(self.media.rglob('*')))
