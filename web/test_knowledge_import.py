from decimal import Decimal
import hashlib
from io import StringIO
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from web.models import Article, ArticleReference


@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={
    'default': {'BACKEND':'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class KnowledgeImportTests(TestCase):
    def import_knowledge(self, **kwargs):
        call_command('import_knowledge', stdout=StringIO(), **kwargs)

    def test_complete_coverage_and_safe_repeat_import(self):
        self.import_knowledge(publish=True)
        items = Article.objects.filter(slug__startswith='heavy-haul-')
        self.assertEqual(items.count(),33)
        self.assertEqual(items.filter(published=True,resource_type__slug='knowledge').count(),33)
        catalog = json.loads((settings.BASE_DIR/'content/knowledge/catalog.json').read_text(encoding='utf-8'))
        source_ids = {s['id'] for a in catalog['entries'] for s in a['source_files'] if s['id'].isdigit()}
        self.assertSetEqual(source_ids,{str(n).zfill(3) for n in range(1,331)})
        self.assertEqual(len({s['path'] for a in catalog['entries'] for s in a['source_files']}),332)
        item = items.get(slug='heavy-haul-axle-loads')
        item.body = 'Administrator-edited text'
        item.original_source = 'PRIVATE ORIGINAL'
        item.published = False
        item.save()
        reference_count = ArticleReference.objects.count()
        self.import_knowledge(publish=True)
        item.refresh_from_db()
        self.assertEqual(item.body,'Administrator-edited text')
        self.assertEqual(item.original_source,'PRIVATE ORIGINAL')
        self.assertFalse(item.published)
        self.assertEqual(items.count(),33)
        self.assertEqual(ArticleReference.objects.count(),reference_count)

    def test_dry_run_and_default_draft_behavior(self):
        self.import_knowledge(dry_run=True,publish=True)
        self.assertFalse(Article.objects.exists())
        self.import_knowledge()
        self.assertEqual(Article.objects.count(),33)
        self.assertFalse(Article.objects.filter(published=True).exists())
        self.assertEqual(self.client.get('/articles/heavy-haul-handbook/').status_code,404)

    def test_pages_filters_sources_and_original_privacy(self):
        self.import_knowledge(publish=True)
        item = Article.objects.get(slug='heavy-haul-china-permits')
        item.original_source='ORIGINAL-PRIVATE-SENTINEL'
        item.editorial_notes='REVIEW-PRIVATE-SENTINEL'
        item.save()
        for item in Article.objects.all():
            response=self.client.get(item.get_absolute_url())
            self.assertEqual(response.status_code,200,item.slug)
            self.assertNotContains(response,'ORIGINAL-PRIVATE-SENTINEL')
            self.assertNotContains(response,'REVIEW-PRIVATE-SENTINEL')
        response=self.client.get('/resources/?type=knowledge&country=china')
        self.assertContains(response,'中国公路大件运输许可')
        response=self.client.get('/articles/heavy-haul-china-permits/')
        self.assertContains(response,'https://xxgk.mot.gov.cn/jigou/fgs/202108/t20210825_3616568.html')
        self.assertNotContains(response,'当天可通关')
        self.assertContains(self.client.get('/resources/?type=knowledge'),'打开专题导读')
        self.assertNotContains(self.client.get('/resources/?type=ports'),'打开专题导读')
        self.assertNotContains(self.client.get('/resources/?type=knowledge&q=ORIGINAL-PRIVATE-SENTINEL'),'中国公路大件运输许可')

    def test_all_internal_article_links_resolve(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            call_command('import_ports',publish_reviewed=True,stdout=StringIO())
            self.import_knowledge(publish=True)
            urls=set()
            for item in Article.objects.filter(slug__startswith='heavy-haul-'):
                urls.update(re.findall(r'\]\((/articles/[^)]+)\)',item.body))
            self.assertGreater(len(urls),32)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code,200,url)

    def test_original_snapshot_hash_is_checked_before_writing(self):
        catalog=json.loads((settings.BASE_DIR/'content/knowledge/catalog.json').read_text(encoding='utf-8'))
        item=catalog['entries'][1]
        with TemporaryDirectory() as temp:
            root=Path(temp)
            raw='Private source text\n原始资料。'.encode()
            source={'id':'001','path':'001-source.md','title':'source','sha256':hashlib.sha256(raw).hexdigest()}
            item['source_files']=[source]
            path=root/'catalog.json'
            path.write_text(json.dumps({'version':1,'source_document_count':1,'entries':[item]}),encoding='utf-8')
            (root/source['path']).write_bytes(b'changed')
            with self.assertRaises(CommandError):
                self.import_knowledge(catalog=path,original_dir=root)
            self.assertFalse(Article.objects.exists())
            (root/source['path']).write_bytes(raw)
            self.import_knowledge(catalog=path,original_dir=root)
            self.assertIn(raw.decode(),Article.objects.get().original_source)

    def test_teaching_arithmetic_and_unit_consistency(self):
        catalog=json.loads((settings.BASE_DIR/'content/knowledge/catalog.json').read_text(encoding='utf-8'))
        bodies={a['slug']:a['body'] for a in catalog['entries']}
        g=Decimal('9.81')
        total=Decimal(80)*g
        rear=(Decimal(60)*g*6+Decimal(20)*g*4)/10
        self.assertEqual(rear,Decimal('431.64'))
        self.assertEqual(total-rear,Decimal('353.16'))
        self.assertIn(str(rear),bodies['heavy-haul-axle-loads'])
        self.assertEqual(Decimal(900)/Decimal(150),Decimal(6))
        self.assertIn('6.0 m²',bodies['heavy-haul-ground-bearing'])
        cost=Decimal(100000)
        self.assertEqual(cost/(1-Decimal('.20')),Decimal(125000))
        finance=(Decimal(1000000)*Decimal('.06')*60/365).quantize(Decimal('.01'))
        self.assertEqual(finance,Decimal('9863.01'))
        self.assertIn('9,863.01',bodies['heavy-haul-margin-and-capital'])
