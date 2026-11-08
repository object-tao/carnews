from io import StringIO
import hashlib
import json
import math
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from web.models import Article, ArticleReference, ResourceType


@override_settings(SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['testserver', 'truck.diwuzhou.cn'], STORAGES={
    'default': {'BACKEND':'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class LoadingRulesTests(TestCase):
    def setUp(self):
        self.catalog = json.loads((settings.BASE_DIR/'content/heavy-cargo/catalog.json').read_text(encoding='utf-8'))

    def load(self, **kwargs):
        call_command('import_loading_rules', stdout=StringIO(), **kwargs)

    def test_separate_category_complete_coverage_and_admin_preservation(self):
        call_command('seed_content', stdout=StringIO())
        original = list(Article.objects.filter(resource_type__slug='knowledge').values())
        self.load(publish=True)
        self.assertEqual(list(Article.objects.filter(resource_type__slug='knowledge').values()), original)
        items = Article.objects.filter(resource_type__slug='heavy-cargo')
        self.assertEqual(items.filter(published=True).count(), 31)
        self.assertEqual(ResourceType.objects.get(slug='heavy-cargo').name, '大件知识')
        self.assertEqual(len({s['path'] for e in self.catalog['entries'] for s in e['source_files']}), 37)
        item = items.get(slug='flatbed-31-ton-loading-limit')
        item.body, item.original_source, item.published = 'Edited by administrator', 'PRIVATE ORIGINAL', False
        item.save()
        item.countries.clear()
        refs = ArticleReference.objects.count()
        self.load(publish=True)
        item.refresh_from_db()
        self.assertEqual(item.body, 'Edited by administrator')
        self.assertEqual(item.original_source, 'PRIVATE ORIGINAL')
        self.assertFalse(item.published)
        self.assertFalse(item.countries.exists())
        self.assertEqual(ArticleReference.objects.count(), refs)
        self.assertEqual(items.count(), 31)

    def test_dry_run_and_default_draft_visibility(self):
        self.load(dry_run=True, publish=True)
        self.assertFalse(Article.objects.exists())
        self.assertFalse(ResourceType.objects.filter(slug='heavy-cargo').exists())
        self.load()
        self.assertFalse(Article.objects.filter(published=True).exists())
        self.assertEqual(self.client.get('/articles/heavy-cargo-handbook/').status_code, 404)
        self.assertNotContains(self.client.get('/resources/?type=heavy-cargo'), '打开大件配载导读')
        self.assertNotContains(self.client.get('/sitemap.xml'), '/articles/heavy-cargo-handbook/')

    def test_public_pages_metadata_links_filters_and_original_privacy(self):
        self.load(publish=True)
        Article.objects.filter(slug='flatbed-31-ton-loading-limit').update(original_source='PRIVATE SOURCE SENTINEL', editorial_notes='PRIVATE REVIEW SENTINEL')
        for entry in self.catalog['entries']:
            response = self.client.get('/articles/' + entry['slug'] + '/')
            self.assertEqual(response.status_code, 200, entry['slug'])
            self.assertContains(response, entry['title'])
            self.assertContains(response, entry['summary'])
            self.assertContains(response, 'https://truck.diwuzhou.cn/articles/' + entry['slug'] + '/')
            self.assertNotContains(response, 'PRIVATE ')
            self.assertNotContains(response, 'source_rule_')
            self.assertNotContains(response, 'admin.ostoa')
            for url in re.findall(r'\]\((/articles/[^)]+)\)', entry['body']):
                if url.strip('/').split('/')[-1] in {'heavy-haul-handbook','vehicle-handbook','bridge-handbook'}:
                    continue
                self.assertEqual(self.client.get(url).status_code, 200, url)
        library = self.client.get('/resources/?type=heavy-cargo')
        self.assertContains(library, '大件知识')
        self.assertContains(library, '打开大件配载导读')
        self.assertEqual(library.context['page'].paginator.count, 31)
        self.assertNotContains(self.client.get('/resources/?type=knowledge'), '打开大件配载导读')
        filtered = self.client.get('/resources/', {'type':'heavy-cargo', 'country':'uzbekistan'})
        self.assertEqual(filtered.context['page'].paginator.count, 2)
        self.assertNotContains(filtered, '打开大件配载导读')
        self.assertEqual(self.client.get('/resources/', {'type':'heavy-cargo','category':'管材规则'}).context['page'].paginator.count, 9)
        self.assertEqual(self.client.get('/resources/', {'type':'heavy-cargo','q':'PRIVATE'}).context['page'].paginator.count, 0)
        sitemap = self.client.get('/sitemap.xml', HTTP_HOST='truck.diwuzhou.cn')
        for entry in self.catalog['entries']:
            self.assertContains(sitemap, 'https://truck.diwuzhou.cn/articles/' + entry['slug'] + '/')

    def test_tampered_original_and_invalid_links_rejected_without_writes(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = b'PRIVATE ORIGINAL DOCUMENT'
            entry = self.catalog['entries'][0]
            entry['source_files'] = [{'path':'original.md', 'sha256':hashlib.sha256(raw).hexdigest()}]
            original = root/'original.md'
            original.write_bytes(b'changed')
            catalog = root/'catalog.json'
            catalog.write_text(json.dumps(self.catalog), encoding='utf-8')
            with self.assertRaises(CommandError):
                self.load(catalog=catalog, original_dir=root)
            self.assertFalse(Article.objects.exists())
            entry['body'] += '\n[Bad link](/articles/not-in-this-collection/)'
            catalog.write_text(json.dumps(self.catalog), encoding='utf-8')
            with self.assertRaises(CommandError):
                self.load(catalog=catalog)
            self.assertFalse(ResourceType.objects.filter(slug='heavy-cargo').exists())

    def test_originals_saved_only_in_admin_and_atomic_rollback(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for entry in self.catalog['entries']:
                for source in entry['source_files']:
                    raw = ('PRIVATE SOURCE ' + source['path']).encode()
                    source['sha256'] = hashlib.sha256(raw).hexdigest()
                    path = root/source['path']
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(raw)
            catalog = root/'catalog.json'
            catalog.write_text(json.dumps(self.catalog), encoding='utf-8')
            clean = Article.full_clean
            def reject_second(article, *args, **kwargs):
                if article.slug == 'indivisible-cargo-44-ton-review':
                    raise ValidationError('Simulated failure after first article')
                return clean(article, *args, **kwargs)
            with patch.object(Article, 'full_clean', reject_second):
                with self.assertRaises(ValidationError):
                    self.load(catalog=catalog, original_dir=root, publish=True)
            self.assertFalse(Article.objects.exists())
            self.assertFalse(ArticleReference.objects.exists())
            self.assertFalse(ResourceType.objects.filter(slug='heavy-cargo').exists())
            self.load(catalog=catalog, original_dir=root, publish=True)
            self.assertEqual(Article.objects.exclude(original_source='').count(), 31)
            self.assertNotContains(self.client.get('/articles/heavy-cargo-handbook/'), 'PRIVATE SOURCE')

    def test_units_and_geometric_examples_preserve_their_boundaries(self):
        bodies = {e['slug']:e['body'] for e in self.catalog['entries']}
        self.assertEqual(20000 / 5000, 4)
        self.assertEqual(2640 / (12000 / 1000), 220)
        self.assertEqual(math.ceil(532000 / 30000), 18)
        self.assertEqual(math.ceil(532000 / 19000), 28)
        self.assertEqual(round(800 * (1 + math.sqrt(3))), 2186)
        self.assertIn('2,186', bodies['pipe-loading-versus-box-envelope'])
        self.assertIn('重量下界', bodies['large-pipe-tarp-safe-19-ton'])
        self.assertIn('不是接触压强', bodies['flatbed-linear-load-4kg-per-mm'])
        self.assertIn('不能据此宣称俄罗斯普通道路统一允许5.2米通行', bodies['russia-vehicle-cargo-height-5200mm'])
        self.assertIn('不能据此证明所有车型均可装44吨货物', bodies['uzbekistan-multi-cargo-44-ton-limit'])
