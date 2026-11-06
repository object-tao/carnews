import copy
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from web.models import Article, ResourceType
from web.port_images import IMAGE_METADATA_FIELDS


@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class PortImageEditionTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.media = self.root / 'media'
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.ports, _ = ResourceType.objects.get_or_create(slug='ports', defaults={'name': '口岸介绍'})

    def article(self, identifier, **values):
        if values.get('published'):
            values.setdefault('published_at', timezone.now())
        return Article.objects.create(
            slug='port-' + identifier, title='Administrator title', kind='resources',
            resource_type=self.ports, category='口岸介绍', summary='Original summary',
            body='Administrator body', original_source='PRIVATE-ORIGINAL',
            **values,
        )

    def backfill(self, **options):
        call_command('backfill_port_images', stdout=StringIO(), **options)

    def test_fills_only_empty_images_and_preserves_edits_and_draft_privacy(self):
        diagram = self.article('0103', published=True)
        photo = self.article('0105', published=False)
        existing = self.article('0104', image='articles/administrator.jpg', image_caption='Keep this credit')
        pending = self.article('0106', image_caption='Administrator image in preparation')
        self.backfill()
        diagram.refresh_from_db()
        photo.refresh_from_db()
        existing.refresh_from_db()
        pending.refresh_from_db()
        self.assertTrue(diagram.image.name.endswith('.png'))
        self.assertTrue(photo.image.name.endswith('.jpg'))
        self.assertEqual(photo.image_taken_on, '2008-10-24')
        self.assertEqual(existing.image.name, 'articles/administrator.jpg')
        self.assertEqual(existing.image_caption, 'Keep this credit')
        self.assertFalse(pending.image)
        self.assertEqual(pending.image_caption, 'Administrator image in preparation')
        for item in (diagram, photo):
            self.assertEqual(item.title, 'Administrator title')
            self.assertEqual(item.body, 'Administrator body')
            self.assertEqual(item.original_source, 'PRIVATE-ORIGINAL')
        page = self.client.get(diagram.get_absolute_url())
        self.assertContains(page, '口岸关系示意图，非实景照片，不按比例')
        self.assertNotContains(page, 'PRIVATE-ORIGINAL')
        self.assertEqual(self.client.get('/article-images/port-0105/?size=card').status_code, 404)
        before = sorted(path.relative_to(self.media) for path in self.media.rglob('*') if path.is_file())
        previous_updated = diagram.updated_at
        self.backfill()
        diagram.refresh_from_db()
        self.assertEqual(diagram.updated_at, previous_updated)
        self.assertEqual(before, sorted(path.relative_to(self.media) for path in self.media.rglob('*') if path.is_file()))
        self.assertTrue(diagram.published)
        self.assertFalse(photo.published)

    def test_dry_run_does_not_save_media_or_metadata(self):
        item = self.article('0103')
        self.backfill(dry_run=True)
        item.refresh_from_db()
        self.assertFalse(item.image)
        self.assertTrue(all(not getattr(item, field) for field in IMAGE_METADATA_FIELDS))
        self.assertFalse(self.media.exists())

    def test_checksum_failure_prevents_any_partial_backfill(self):
        self.article('0103')
        self.article('0105')
        original = json.loads((settings.BASE_DIR / 'content/ports/image-edition-20261107.json').read_text(encoding='utf-8'))
        edition = copy.deepcopy(original)
        edition['entries'][-1]['sha256'] = '0' * 64
        path = self.root / 'tampered-edition.json'
        path.write_text(json.dumps(edition), encoding='utf-8')
        with self.assertRaises(CommandError):
            self.backfill(edition=path)
        self.assertFalse(Article.objects.exclude(image='').exists())
        self.assertFalse(self.media.exists())

    def test_storage_failure_rolls_back_rows_and_removes_new_files(self):
        self.article('0103')
        self.article('0105')
        real_save = FileSystemStorage._save
        count = 0

        def failing_second_save(storage, name, content):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('Simulated storage unavailable')
            return real_save(storage, name, content)

        with patch.object(FileSystemStorage, '_save', failing_second_save):
            with self.assertRaises(OSError):
                self.backfill()
        self.assertFalse(Article.objects.exclude(image='').exists())
        self.assertFalse(any(path.is_file() for path in self.media.rglob('*')))
