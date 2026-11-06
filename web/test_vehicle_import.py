from decimal import Decimal
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


@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={
    'default': {'BACKEND':'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class VehicleImportTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media = Path(self.temp.name)/'media'
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.catalog_path = settings.BASE_DIR/'content/vehicles/catalog.json'
        self.catalog = json.loads(self.catalog_path.read_text(encoding='utf-8'))

    def import_vehicles(self, **kwargs):
        call_command('import_vehicles', stdout=StringIO(), **kwargs)

    def test_dry_run_and_drafts_do_not_publish_articles_or_images(self):
        self.import_vehicles(dry_run=True, publish=True)
        self.assertFalse(Article.objects.exists())
        self.assertFalse(self.media.exists())
        self.import_vehicles()
        self.assertEqual(Article.objects.count(),21)
        self.assertFalse(Article.objects.filter(published=True).exists())
        self.assertEqual(self.client.get('/articles/vehicle-01/').status_code,404)
        self.assertEqual(self.client.get('/article-images/vehicle-01/').status_code,404)
        self.assertNotContains(self.client.get('/sitemap.xml'),'/articles/vehicle-01/')

    def test_complete_image_mapping_and_safe_repeat(self):
        self.import_vehicles(publish=True)
        items=Article.objects.filter(resource_type__slug='vehicles')
        self.assertEqual(items.filter(published=True).count(),21)
        self.assertEqual(items.exclude(image='').count(),19)
        self.assertEqual(len({s['path'] for e in self.catalog['entries'] for s in e['source_files']}),22)
        for entry in self.catalog['entries']:
            item=items.get(slug=entry['slug'])
            self.assertTrue(item.references.exists())
            if entry['photo']:
                with item.image.open('rb') as image:
                    self.assertEqual(hashlib.sha256(image.read()).hexdigest(),entry['photo']['sha256'])
                self.assertIn('AI',item.image_note)
                self.assertEqual(item.image_license,'')
                self.assertEqual(item.image_taken_on,'')
        before_files=sorted(str(p) for p in self.media.rglob('*') if p.is_file())
        before_references=ArticleReference.objects.count()
        item=items.get(slug='vehicle-01')
        item.body='Administrator revised body'
        item.image_note='Administrator revised image note'
        item.published=False
        item.save()
        self.import_vehicles(publish=True)
        item.refresh_from_db()
        self.assertEqual(item.body,'Administrator revised body')
        self.assertEqual(item.image_note,'Administrator revised image note')
        self.assertFalse(item.published)
        self.assertEqual(ArticleReference.objects.count(),before_references)
        self.assertEqual(before_files,sorted(str(p) for p in self.media.rglob('*') if p.is_file()))

    def test_public_pages_ai_credit_privacy_filters_and_guide(self):
        call_command('import_knowledge', publish=True, stdout=StringIO())
        self.import_vehicles(publish=True)
        item=Article.objects.get(slug='vehicle-18')
        item.original_source='PRIVATE VEHICLE ORIGINAL'
        item.editorial_notes='PRIVATE VEHICLE REVIEW'
        item.save()
        for item in Article.objects.filter(resource_type__slug='vehicles'):
            response=self.client.get(item.get_absolute_url())
            self.assertEqual(response.status_code,200,item.slug)
            self.assertNotContains(response,'PRIVATE VEHICLE')
            if item.image:
                self.assertContains(response,'AI生成车型示意图')
                self.assertNotContains(response,'历史实景资料图')
                image=self.client.get('/article-images/'+item.slug+'/')
                self.assertEqual(image.status_code,200)
                image.close()
            for url in re.findall(r'\]\((/articles/[^)]+)\)',item.body):
                self.assertEqual(self.client.get(url).status_code,200,url)
        library=self.client.get('/resources/?type=vehicles')
        self.assertContains(library,'打开车型选型指南')
        self.assertContains(library,'AI生成车型示意图')
        self.assertNotContains(self.client.get('/resources/?type=knowledge'),'打开车型选型指南')
        self.assertNotContains(self.client.get('/resources/?type=vehicles&q=PRIVATE VEHICLE'),'Mega升降顶')
        filtered=self.client.get('/resources/',{'type':'vehicles','category':'车型·大件特种'})
        self.assertEqual(filtered.context['page'].paginator.count,7)
        self.assertNotContains(filtered,'打开车型选型指南')

    def test_original_and_image_hashes_are_checked_before_writes(self):
        root=Path(self.temp.name)
        item=self.catalog['entries'][1]
        photo=item['photo']
        image=(self.catalog_path.parent/photo['file']).read_bytes()
        (root/photo['file']).parent.mkdir(parents=True)
        (root/photo['file']).write_bytes(image)
        original_dir=root/'original'
        (original_dir/photo['source_file']).parent.mkdir(parents=True)
        (original_dir/photo['source_file']).write_bytes(image)
        raw='PRIVATE ORIGINAL DOC'.encode()
        item['source_files']=[{'path':'original.md','sha256':hashlib.sha256(raw).hexdigest()}]
        catalog=root/'one.json'
        catalog.write_text(json.dumps({'version':1,'source_document_count':1,'image_count':1,'entries':[item]}),encoding='utf-8')
        (original_dir/'original.md').write_bytes(b'changed source')
        with self.assertRaises(CommandError):
            self.import_vehicles(catalog=catalog,original_dir=original_dir)
        self.assertFalse(Article.objects.exists())
        (original_dir/'original.md').write_bytes(raw)
        (root/photo['file']).write_bytes(b'changed image')
        with self.assertRaises(CommandError):
            self.import_vehicles(catalog=catalog,original_dir=original_dir)
        self.assertFalse(self.media.exists())
        (root/photo['file']).write_bytes(image)
        self.import_vehicles(catalog=catalog,original_dir=original_dir,publish=True)
        self.assertIn(raw.decode(),Article.objects.get().original_source)
        self.assertNotContains(self.client.get('/articles/vehicle-01/'),raw.decode())

    def test_failure_rolls_back_database_and_only_new_media(self):
        self.media.mkdir()
        retained=self.media/'existing-user-file.txt'
        retained.write_text('keep',encoding='utf-8')
        full_clean=Article.full_clean
        def reject_second_vehicle(article,*args,**kwargs):
            if article.slug=='vehicle-02':
                raise ValidationError('Simulated invalid article after the first image was saved')
            return full_clean(article,*args,**kwargs)
        with patch.object(Article,'full_clean',reject_second_vehicle):
            with self.assertRaises(ValidationError):
                self.import_vehicles(publish=True)
        self.assertFalse(Article.objects.exists())
        self.assertFalse(ArticleReference.objects.exists())
        self.assertEqual([p for p in self.media.rglob('*') if p.is_file()],[retained])

    def test_editorial_calculations_distinguish_limits_from_layout(self):
        entries={e['slug']:e for e in self.catalog['entries']}
        calculation=entries['vehicle-loading-calculation']['body']
        for height in ('2.70','2.80','2.95','3.00'):
            volume=Decimal('13.62')*Decimal('2.48')*Decimal(height)
            self.assertIn(format(volume.normalize(),'f'),calculation)
        self.assertIn('1,055箱',calculation)
        self.assertIn('必要条件形成的上限',calculation)
        self.assertIn('22×6×7＝924箱',calculation)
        self.assertIn('不是最优解',calculation)
        self.assertIn('99.96立方米',entries['vehicle-19']['body'])
