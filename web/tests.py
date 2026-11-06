from datetime import timedelta
import json
from tempfile import TemporaryDirectory
from django.test import TestCase, override_settings
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from .models import Article, Route

@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class WebsiteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_content',verbosity=0)
    def test_public_pages(self):
        for url in ['/','/routes/','/about/','/contact/','/news/','/resources/','/robots.txt','/sitemap.xml','/healthz/','/admin/login/']:
            with self.subTest(url=url): self.assertEqual(self.client.get(url).status_code,200)
    def test_all_details(self):
        for item in [*Route.objects.all(),*Article.objects.all()]:
            self.assertEqual(self.client.get(item.get_absolute_url()).status_code,200)
    def test_drafts_and_future_articles_are_private(self):
        for slug,published,date in [('draft',False,timezone.now()),('future',True,timezone.now()+timedelta(days=2))]:
            item=Article.objects.create(title='PRIVATE SENTINEL',slug=slug,kind='news',summary='hidden',body='secret',published=published,published_at=date)
            self.assertEqual(self.client.get(item.get_absolute_url()).status_code,404)
            self.assertEqual(self.client.get('/download/'+slug+'/').status_code,404)
            self.assertNotContains(self.client.get('/sitemap.xml'),item.get_absolute_url())
            self.assertNotContains(self.client.get('/news/'),'PRIVATE SENTINEL')
        route=Route.objects.create(title='private',slug='private',region='asia',countries='test',summary='test',body='test')
        self.assertEqual(self.client.get(route.get_absolute_url()).status_code,404)
    def test_search_and_region_filter(self):
        self.assertContains(self.client.get('/resources/?q=询价'),'整车运输询价')
        self.assertNotContains(self.client.get('/resources/?q=不存在的词'),'整车运输询价')
        response=self.client.get('/routes/?region=asia')
        self.assertContains(response,'中国—中亚')
        self.assertNotContains(response,'中国—欧洲及英国')
    def test_article_body_and_schema_are_safe(self):
        item=Article.objects.first()
        item.body='<script>alert(1)</script>'
        item.title='</script><script>alert(2)</script>'
        item.save()
        response=self.client.get(item.get_absolute_url())
        self.assertNotContains(response,'<script>alert(')
        text=response.content.decode()
        schema=text.split('<script type="application/ld+json">')[1].split('</script>')[0]
        self.assertEqual(json.loads(schema)['headline'],item.title)
    def test_attachment_authorization(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            item=Article.objects.first()
            item.attachment=SimpleUploadedFile('guide.pdf',b'%PDF-1.4 sample')
            item.save()
            response=self.client.get('/download/'+item.slug+'/')
            self.assertEqual(response.status_code,200)
            self.assertIn('attachment',response['Content-Disposition'])
            response.close()
            item.published=False; item.save()
            self.assertEqual(self.client.get('/download/'+item.slug+'/').status_code,404)
    def test_seed_is_idempotent(self):
        item=Article.objects.first(); item.title='管理员的修改'; item.save()
        call_command('seed_content',verbosity=0)
        item.refresh_from_db()
        self.assertEqual(item.title,'管理员的修改')
        self.assertEqual(Article.objects.count(),6)
    def test_admin_requires_login_and_csrf(self):
        from django.test import Client
        self.assertEqual(self.client.get('/admin/web/article/').status_code,302)
        self.assertEqual(Client(enforce_csrf_checks=True).post('/admin/login/',{'username':'x','password':'x'}).status_code,403)
