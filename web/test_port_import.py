import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from web.models import Article, ArticleReference, Country
from web.templatetags.content import article_body


@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={
    'default': {'BACKEND':'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class PortImportTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media = Path(self.temp.name) / 'media'
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.addCleanup(self.override.disable)

    def import_ports(self, **kwargs):
        call_command('import_ports', stdout=StringIO(), **kwargs)

    def test_catalog_import_country_corrections_and_repeat_safety(self):
        self.import_ports(publish_reviewed=True)
        self.assertEqual(Article.objects.count(), 66)
        self.assertEqual(Article.objects.filter(published=True).count(), 66)
        call_command('publish_reviewed_ports', stdout=StringIO())
        self.assertEqual(Article.objects.filter(published=True).count(), 66)
        self.assertEqual(Article.objects.exclude(image='').count(), 66)
        item = Article.objects.get(slug='port-0106')
        self.assertSetEqual(set(item.countries.values_list('slug', flat=True)), {'china', 'kazakhstan'})
        self.assertIn('巴里坤', Article.objects.get(slug='port-0113').location)
        item.body = 'Administrator edited this content'
        item.published = False
        item.save()
        before_files = sorted(str(p) for p in self.media.rglob('*') if p.is_file())
        before_references = ArticleReference.objects.count()
        self.import_ports(publish_reviewed=True)
        item.refresh_from_db()
        self.assertEqual(item.body, 'Administrator edited this content')
        self.assertFalse(item.published)
        self.assertEqual(Article.objects.count(), 66)
        self.assertEqual(ArticleReference.objects.count(), before_references)
        self.assertEqual(before_files, sorted(str(p) for p in self.media.rglob('*') if p.is_file()))

    def test_dry_run_has_no_database_or_media_side_effects(self):
        before = Country.objects.count()
        self.import_ports(dry_run=True, publish_reviewed=True)
        self.assertEqual(Article.objects.count(), 0)
        self.assertEqual(Country.objects.count(), before)
        self.assertFalse(self.media.exists())

    def test_default_does_not_publish(self):
        self.import_ports()
        self.assertEqual(Article.objects.count(), 66)
        self.assertFalse(Article.objects.filter(published=True).exists())

    def test_public_sources_and_photo_credit_and_draft_privacy(self):
        self.import_ports(publish_reviewed=True)
        item = Article.objects.get(slug='port-0102')
        item.original_source = 'PRIVATE-ORIGINAL-SENTINEL'
        item.editorial_notes = 'PRIVATE-REVIEW-SENTINEL'
        item.save()
        page = self.client.get(item.get_absolute_url())
        self.assertContains(page, '<table>')
        self.assertContains(page, '资料来源与核对范围')
        self.assertContains(page, item.image_license)
        self.assertContains(page, '历史实景资料图')
        self.assertNotContains(page, 'PRIVATE-ORIGINAL-SENTINEL')
        self.assertNotContains(page, 'PRIVATE-REVIEW-SENTINEL')
        image = self.client.get('/article-images/port-0102/')
        self.assertEqual(image.status_code, 200)
        image.close()
        item.published = False
        item.save()
        self.assertEqual(self.client.get('/article-images/port-0102/').status_code, 404)
        self.assertEqual(self.client.get('/articles/port-0102/').status_code, 404)
        self.assertNotContains(self.client.get('/sitemap.xml'), '/articles/port-0102/')
        self.assertNotContains(self.client.get('/resources/?q=PRIVATE-ORIGINAL-SENTINEL'), item.title)

    def test_original_is_preserved_privately(self):
        bundle = json.loads((settings.BASE_DIR/'content/ports/catalog.json').read_text(encoding='utf-8'))
        item = bundle['entries'][2]
        item['photo'] = None
        catalog = Path(self.temp.name)/'one.json'
        catalog.write_text(json.dumps({'version':1, 'entries':[item]}), encoding='utf-8')
        originals = Path(self.temp.name)/'originals'
        original = originals/item['source_file']
        original.parent.mkdir(parents=True)
        original.write_text('Original text\n原始资料完整保存。', encoding='utf-8')
        self.import_ports(catalog=catalog, original_dir=originals)
        self.assertEqual(Article.objects.get().original_source, original.read_text(encoding='utf-8'))

    def test_original_path_cannot_escape_selected_directory(self):
        bundle = json.loads((settings.BASE_DIR/'content/ports/catalog.json').read_text(encoding='utf-8'))
        item = bundle['entries'][0]
        item['source_file'] = '../outside.md'
        root = Path(self.temp.name)
        (root/'outside.md').write_text('private', encoding='utf-8')
        (root/'source').mkdir()
        catalog = root/'invalid.json'
        catalog.write_text(json.dumps({'version':1, 'entries':[item]}), encoding='utf-8')
        with self.assertRaises(CommandError):
            self.import_ports(catalog=catalog, original_dir=root/'source')
        self.assertFalse(Article.objects.exists())

    def test_markdown_cannot_execute_html_or_script_links(self):
        item = Article(body_format='markdown', body='## Title\n\n<script>alert(1)</script>\n\n[bad](javascript:alert)\n\n<img src=x onerror=alert(1)>\n\n**bold**')
        html = str(article_body(item))
        self.assertIn('<h2>Title</h2>', html)
        self.assertIn('<strong>bold</strong>', html)
        self.assertNotIn('<script', html)
        self.assertNotIn('<img', html)
        self.assertNotIn('href="javascript:', html)
        item.body_format = 'text'
        item.body = '<script>bad()</script>'
        self.assertNotIn('<script', str(article_body(item)))
