from io import StringIO
import copy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from web.models import Article, ArticleReference, ResourceType


@override_settings(SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['testserver', 'truck.diwuzhou.cn'], STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class CountryResearchTests(TestCase):
    def setUp(self):
        self.catalog = json.loads((settings.BASE_DIR/'content/country-rules/catalog.json').read_text(encoding='utf-8'))

    def load(self, **kwargs):
        call_command('import_country_rules', stdout=StringIO(), **kwargs)

    def test_complete_coverage_preserves_existing_content_and_admin_decisions(self):
        call_command('import_loading_rules', publish=True, stdout=StringIO())
        original = list(Article.objects.values())
        self.load(publish=True)
        self.assertEqual(Article.objects.count(), 97)
        self.assertEqual(list(Article.objects.filter(pk__in=[a['id'] for a in original]).values()), original)
        countries = Article.objects.filter(slug__endswith='-heavy-haul-transport-rules')
        self.assertEqual(countries.count(), 64)
        self.assertEqual([countries.filter(evidence_level=x).count() for x in 'ABC'], [44,18,2])
        self.assertTrue(all(a.countries.count() == 1 for a in countries))
        item = countries.get(slug='ir-heavy-haul-transport-rules')
        item.body, item.evidence_level, item.published = 'Administrator edit', 'B', False
        item.save()
        item.references.all().delete()
        before = list(Article.objects.values())
        refs = ArticleReference.objects.count()
        self.load(publish=True)
        self.assertEqual(list(Article.objects.values()), before)
        self.assertEqual(ArticleReference.objects.count(), refs)

    def test_public_evidence_notices_guide_country_filters_and_sitemap(self):
        self.load(publish=True)
        Article.objects.update(original_source='PRIVATE ORIGINAL SENTINEL', editorial_notes='PRIVATE REVIEW SENTINEL')
        for entry in self.catalog['entries']:
            page = self.client.get('/articles/'+entry['slug']+'/')
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, entry['title'])
            self.assertNotContains(page, 'PRIVATE ORIGINAL SENTINEL')
            self.assertNotContains(page, 'PRIVATE REVIEW SENTINEL')
            self.assertNotContains(page, 'publication_review_required')
            if entry['evidence_level']:
                self.assertContains(page, 'evidence-'+entry['evidence_level'])
                self.assertContains(page, '研究资料 ·')
            if entry['countries']:
                listing = self.client.get('/resources/', {'type':'heavy-cargo','country':entry['countries'][0]})
                self.assertContains(listing, entry['title'])
                self.assertContains(listing, 'evidence-badge')
        self.assertContains(self.client.get('/resources/?type=heavy-cargo'), '查看64国运输规则')
        self.assertContains(self.client.get('/resources/?type=heavy-cargo&country=iran'), '直接依据待补')
        self.assertContains(self.client.get('/resources/?type=heavy-cargo&country=belarus'), '依据不完整')
        sitemap = self.client.get('/sitemap.xml')
        for entry in self.catalog['entries']:
            self.assertContains(sitemap, '/articles/'+entry['slug']+'/')

    def test_dry_run_and_drafts_are_not_published_implicitly(self):
        self.load(dry_run=True)
        self.assertFalse(Article.objects.exists())
        self.load()
        self.assertFalse(Article.objects.filter(published=True).exists())
        self.assertEqual(self.client.get('/articles/ir-heavy-haul-transport-rules/').status_code, 404)
        self.assertNotContains(self.client.get('/resources/?type=heavy-cargo'), '查看64国运输规则')
        self.assertNotContains(self.client.get('/sitemap.xml'), '/articles/country-heavy-haul-handbook/')
        self.load(publish=True)
        self.assertFalse(Article.objects.filter(published=True).exists())

    def test_private_original_checksums_and_invalid_catalog_fail_before_mutation(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            bundle = copy.deepcopy(self.catalog)
            for entry in bundle['entries']:
                for source in entry['source_files']:
                    raw = ('PRIVATE ORIGINAL '+source['path']).encode()
                    source['sha256'] = hashlib.sha256(raw).hexdigest()
                    path = base/source['path']
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(raw)
            catalog = base/'catalog.json'
            catalog.write_text(json.dumps(bundle), encoding='utf-8')
            damaged = base/bundle['entries'][0]['source_files'][0]['path']
            correct = damaged.read_bytes()
            damaged.write_bytes(b'wrong')
            with self.assertRaises(CommandError):
                self.load(catalog=catalog, original_dir=base, publish=True)
            self.assertFalse(Article.objects.exists())
            self.assertFalse(ResourceType.objects.filter(slug='heavy-cargo').exists())
            damaged.write_bytes(correct)
            bundle['entries'][0]['evidence_level'] = 'X'
            catalog.write_text(json.dumps(bundle), encoding='utf-8')
            with self.assertRaises(CommandError):
                self.load(catalog=catalog, original_dir=base, publish=True)
            self.assertFalse(Article.objects.exists())
            bundle['entries'][0]['evidence_level'] = 'A'
            catalog.write_text(json.dumps(bundle), encoding='utf-8')
            self.load(catalog=catalog, original_dir=base, publish=True)
            self.assertEqual(Article.objects.exclude(original_source='').count(), 66)
            self.assertNotContains(self.client.get('/articles/country-heavy-haul-handbook/'), 'PRIVATE ORIGINAL')

    def test_numerical_claims_retain_their_material_boundaries(self):
        entries = {e['id']:e for e in self.catalog['entries']}
        self.assertIn('含车辆与货物', entries['UZ']['body'])
        self.assertIn('五轴', entries['UZ']['body'])
        self.assertIn('EU/EEA', entries['FI']['body'])
        self.assertIn('申请触发值，非普通', entries['BH']['body'])
        self.assertIn('历史参数，现行性待核', entries['YE']['body'])
        self.assertIn('当前全面恢复实施', entries['AE']['body'])
        self.assertIn('本次发布复核时', entries['KZ']['body'])
        self.assertIn('本次发布复核时', entries['EG']['body'])
        self.assertIn('缺少数值不表示没有限制', entries['IR']['body'])
        self.assertIn('不是已批准的运输案例', entries['KM']['body'])
