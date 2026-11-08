import hashlib
from io import StringIO
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from web.models import Article, ArticleReference


@override_settings(SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['testserver', 'truck.diwuzhou.cn'], STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class BridgeImportTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.media = self.root / 'media'
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.catalog_path = settings.BASE_DIR / 'content/bridges/catalog.json'
        self.catalog = json.loads(self.catalog_path.read_text(encoding='utf-8'))

    def import_bridges(self, **kwargs):
        call_command('import_bridges', stdout=StringIO(), **kwargs)

    def test_dry_run_and_drafts_remain_private(self):
        self.import_bridges(dry_run=True, publish=True)
        self.assertFalse(Article.objects.exists())
        self.assertFalse(self.media.exists())
        self.import_bridges()
        self.assertEqual(Article.objects.count(), 73)
        self.assertFalse(Article.objects.filter(published=True).exists())
        self.assertEqual(self.client.get('/articles/bridge-0101/').status_code, 404)
        self.assertEqual(self.client.get('/article-images/bridge-0101/').status_code, 404)
        self.assertNotContains(self.client.get('/sitemap.xml'), '/articles/bridge-0101/')
        self.assertNotContains(self.client.get('/resources/?type=bridges'), '打开桥涵节点导读')

    def test_image_mapping_and_repeat_preserve_admin_changes(self):
        self.import_bridges(publish=True)
        items = Article.objects.filter(resource_type__slug='bridges')
        self.assertEqual(items.filter(published=True).count(), 73)
        self.assertEqual(items.exclude(image='').count(), 73)
        for entry in self.catalog['entries']:
            item = items.get(slug=entry['slug'])
            with item.image.open('rb') as image:
                self.assertEqual(hashlib.sha256(image.read()).hexdigest(), entry['photo']['sha256'])
            self.assertTrue(item.references.exists())
            self.assertEqual(item.image_taken_on, '')
        files = sorted(p.relative_to(self.media).as_posix() for p in self.media.rglob('*') if p.is_file())
        refs = ArticleReference.objects.count()
        item = items.get(slug='bridge-0101')
        item.body = 'Administrator revised body'
        item.original_source = 'PRIVATE ORIGINAL'
        item.image_note = 'Administrator revised illustration credit'
        item.published = False
        item.save()
        item.countries.clear()
        self.import_bridges(publish=True)
        item.refresh_from_db()
        self.assertEqual(item.body, 'Administrator revised body')
        self.assertEqual(item.original_source, 'PRIVATE ORIGINAL')
        self.assertEqual(item.image_note, 'Administrator revised illustration credit')
        self.assertFalse(item.published)
        self.assertFalse(item.countries.exists())
        self.assertEqual(ArticleReference.objects.count(), refs)
        self.assertEqual(files, sorted(p.relative_to(self.media).as_posix() for p in self.media.rglob('*') if p.is_file()))

    def test_public_library_filters_guide_sitemap_and_private_notes(self):
        self.import_bridges(publish=True)
        Article.objects.filter(slug='bridge-0101').update(original_source='PRIVATE BRIDGE ORIGINAL', editorial_notes='PRIVATE BRIDGE REVIEW')
        for item in Article.objects.all():
            response = self.client.get(item.get_absolute_url())
            self.assertEqual(response.status_code, 200, item.slug)
            self.assertContains(response, 'AI生成，非现场实拍')
            self.assertNotContains(response, 'PRIVATE BRIDGE')
        guide = Article.objects.get(slug='bridge-handbook')
        links = re.findall(r'\]\((/articles/bridge-\d+/)\)', guide.body)
        self.assertEqual(len(set(links)), 72)
        for url in links:
            self.assertTrue(Article.objects.filter(slug=url.split('/')[2], published=True).exists())
        library = self.client.get('/resources/?type=bridges')
        self.assertContains(library, '打开桥涵节点导读')
        self.assertEqual(library.context['page'].paginator.count, 73)
        expected = sum('georgia' in e['countries'] for e in self.catalog['entries'])
        filtered = self.client.get('/resources/', {'type': 'bridges', 'country': 'georgia'})
        self.assertGreater(expected, 0)
        self.assertEqual(filtered.context['page'].paginator.count, expected)
        self.assertNotContains(filtered, '打开桥涵节点导读')
        self.assertNotContains(self.client.get('/resources/?type=knowledge'), '打开桥涵节点导读')
        self.assertEqual(self.client.get('/resources/?type=bridges&q=PRIVATE BRIDGE').context['page'].paginator.count, 0)
        sitemap = self.client.get('/sitemap.xml', HTTP_HOST='truck.diwuzhou.cn')
        for item in Article.objects.all():
            self.assertContains(sitemap, 'https://truck.diwuzhou.cn' + item.get_absolute_url())
        for variant in ('', '?size=card', '?size=detail'):
            image = self.client.get('/article-images/bridge-0101/' + variant)
            self.assertEqual(image.status_code, 200)
            image.close()

    def fixture_catalog(self):
        entry = self.catalog['entries'][0]
        photo = entry['photo']
        target = self.root / photo['file']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((self.catalog_path.parent / photo['file']).read_bytes())
        raw = b'PRIVATE ORIGINAL BRIDGE DOCUMENT'
        entry['source_files'] = [{'path': 'original.md', 'sha256': hashlib.sha256(raw).hexdigest()}]
        self.catalog.update(entries=[entry], source_document_count=1, image_count=1)
        path = self.root / 'one.json'
        original_dir = self.root / 'originals'
        original_dir.mkdir()
        (original_dir / 'original.md').write_bytes(raw)
        return path, original_dir, entry, target

    def test_tampered_sources_images_and_disclosures_rejected_before_writes(self):
        path, originals, entry, image = self.fixture_catalog()
        original_bytes = (originals / 'original.md').read_bytes()
        image_bytes = image.read_bytes()
        for problem in ('source', 'image', 'disclosure', 'path'):
            with self.subTest(problem=problem):
                (originals / 'original.md').write_bytes(original_bytes)
                image.write_bytes(image_bytes)
                photo = entry['photo'].copy()
                if problem == 'source':
                    (originals / 'original.md').write_bytes(b'changed')
                elif problem == 'image':
                    image.write_bytes(b'changed')
                elif problem == 'disclosure':
                    entry['photo']['caption'] = 'A real bridge photograph'
                else:
                    entry['photo']['file'] = '../outside.webp'
                path.write_text(json.dumps(self.catalog), encoding='utf-8')
                with self.assertRaises(CommandError):
                    self.import_bridges(catalog=path, original_dir=originals, publish=True)
                self.assertFalse(Article.objects.exists())
                self.assertFalse(self.media.exists())
                entry['photo'] = photo
        path.write_text(json.dumps(self.catalog), encoding='utf-8')
        self.import_bridges(catalog=path, original_dir=originals, publish=True)
        self.assertIn(original_bytes.decode(), Article.objects.get().original_source)
        self.assertNotContains(self.client.get('/articles/bridge-0101/'), original_bytes.decode())

    def test_partial_failure_rolls_back_database_and_new_media_only(self):
        self.media.mkdir()
        retained = self.media / 'existing-user-file.txt'
        retained.write_text('keep', encoding='utf-8')
        full_clean = Article.full_clean

        def reject_second(article, *args, **kwargs):
            if article.slug == 'bridge-0102':
                raise ValidationError('Simulated second article failure')
            return full_clean(article, *args, **kwargs)

        with patch.object(Article, 'full_clean', reject_second):
            with self.assertRaises(ValidationError):
                self.import_bridges(publish=True)
        self.assertFalse(Article.objects.exists())
        self.assertFalse(ArticleReference.objects.exists())
        self.assertEqual([p for p in self.media.rglob('*') if p.is_file()], [retained])
