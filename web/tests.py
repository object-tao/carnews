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


@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class LibraryAndRateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from .models import Country, ResourceType, FreightRate
        from django.contrib.auth import get_user_model
        call_command('seed_content',verbosity=0)
        cls.china=Country.objects.get(slug='china')
        cls.kazakhstan=Country.objects.get(slug='kazakhstan')
        cls.port_type=ResourceType.objects.get(slug='ports')
        cls.resource=Article.objects.create(title='跨境口岸验收资料',slug='port-fixture',kind='resources',resource_type=cls.port_type,summary='资料摘要',body='资料正文',location='位置验收',restrictions='通行限制验收',published=True,published_at=timezone.now())
        cls.resource.countries.add(cls.china,cls.kazakhstan)
        cls.route=Route.objects.get(slug='central-asia')
        cls.route.country_tags.add(cls.china,cls.kazakhstan)
        cls.resource.related_routes.add(cls.route)
        today=timezone.localdate()
        for slug,start,end in [('current',today,today),('expired',today-timedelta(days=4),today-timedelta(days=1)),('upcoming',today+timedelta(days=1),today+timedelta(days=4))]:
            FreightRate.objects.create(route=cls.route,slug=slug,origin='验收装货地',destination='验收卸货地',vehicle='验收车型',cargo='验收货物',price_min=100,price_max=120,terms='费用条件验收',source='自动化测试数据',valid_from=start,valid_until=end,published=True,published_at=timezone.now())
        cls.admin=get_user_model().objects.create_superuser('qa-admin','qa@example.test','test-only-password-never-used-in-production')
    def test_resource_country_and_type_combination(self):
        for country in ['china','kazakhstan']:
            response=self.client.get('/resources/',{'type':'ports','country':country,'q':'跨境口岸'})
            self.assertEqual(len(response.context['page']),1)
            self.assertContains(response,self.resource.title)
        response=self.client.get('/resources/?type=bridges&country=china')
        self.assertEqual(len(response.context['page']),0)
        self.assertContains(response,'没有找到匹配内容')
    def test_shared_route_and_live_edits(self):
        self.route.title='已更新的共用线路';self.route.save()
        self.assertContains(self.client.get('/resources/?type=routes&country=kazakhstan'),'已更新的共用线路')
        self.assertContains(self.client.get(self.route.get_absolute_url()),'已更新的共用线路')
        self.route.published=False;self.route.save()
        self.assertNotContains(self.client.get('/resources/?type=routes'),'已更新的共用线路')
    def test_country_filters_cannot_duplicate_cards(self):
        response=self.client.get('/resources/?q=中国')
        ids=[x.pk for x in response.context['page']]
        self.assertEqual(len(ids),len(set(ids)))
    def test_custom_resource_type_and_pagination_keep_filters(self):
        from .models import ResourceType
        custom=ResourceType.objects.create(name='新增专业资料',slug='custom')
        for i in range(10):
            item=Article.objects.create(title=f'新增资料{i}',slug=f'custom-{i}',kind='resources',resource_type=custom,category='验收分类',summary='摘要',body='正文',published=True,published_at=timezone.now())
            item.countries.add(self.china)
        response=self.client.get('/resources/?type=custom&country=china&category=验收分类&q=新增')
        self.assertEqual(response.context['page'].paginator.count,10)
        self.assertContains(response,'type=custom')
        self.assertContains(response,'country=china')
        self.assertContains(response,'page=2')
        response=self.client.get('/resources/',{'type':'custom','country':'china','category':'验收分类','q':'新增','page':2})
        self.assertEqual(len(response.context['page']),1)
    def test_private_related_content_not_leaked(self):
        hidden=Article.objects.create(title='HIDDEN RELATION',slug='hidden-link',kind='resources',summary='x',body='x')
        self.resource.related_resources.add(hidden)
        self.assertNotContains(self.client.get(self.resource.get_absolute_url()),'HIDDEN RELATION')
        self.resource.published=False;self.resource.save()
        self.assertNotContains(self.client.get(self.route.get_absolute_url()),self.resource.title)
    def test_resource_details(self):
        response=self.client.get(self.resource.get_absolute_url())
        for text in ['位置验收','通行限制验收','中国','哈萨克斯坦',self.route.title]: self.assertContains(response,text)
    def test_rate_status_and_date_boundaries(self):
        from .models import FreightRate
        for slug,label in [('current','有效期内'),('expired','已过期'),('upcoming','尚未生效')]:
            rate=FreightRate.objects.get(slug=slug)
            response=self.client.get(rate.get_absolute_url())
            self.assertContains(response,label)
            self.assertContains(response,'费用条件验收')
            self.assertContains(response,'自动化测试数据')
            if slug=='expired': self.assertContains(response,'不作为当前报价')
        for status,expected in [('valid','current'),('expired','expired'),('upcoming','upcoming')]:
            response=self.client.get('/prices/',{'status':status,'country':'china','q':'验收车型'})
            self.assertEqual([r.slug for r in response.context['page']],[expected])
    def test_rate_drafts_scheduled_and_unpublished_routes_hidden(self):
        from .models import FreightRate
        rate=FreightRate.objects.get(slug='current')
        rate.published=False;rate.save()
        self.assertEqual(self.client.get(rate.get_absolute_url()).status_code,404)
        self.assertNotContains(self.client.get('/sitemap.xml'),rate.get_absolute_url())
        rate.published=True;rate.published_at=timezone.now()+timedelta(days=1);rate.save()
        self.assertEqual(self.client.get(rate.get_absolute_url()).status_code,404)
        self.route.published=False;self.route.save()
        self.assertEqual(len(self.client.get('/prices/').context['page']),0)
    def test_rate_validation(self):
        from .models import FreightRate, ResourceType
        from django.core.exceptions import ValidationError
        rate=FreightRate.objects.get(slug='current')
        for field,value in [('price_max',50),('price_min',-1),('valid_until',timezone.localdate()-timedelta(days=1))]:
            with self.subTest(field=field):
                rate.refresh_from_db();setattr(rate,field,value)
                with self.assertRaises(ValidationError): rate.full_clean()
        with self.assertRaises(ValidationError): ResourceType(name='保留类型',slug='routes').full_clean()
    def test_admin_add_and_edit_forms(self):
        self.client.force_login(self.admin)
        for url in ['/admin/web/country/add/','/admin/web/resourcetype/add/','/admin/web/freightrate/add/',f'/admin/web/article/{self.resource.pk}/change/']:
            with self.subTest(url=url): self.assertEqual(self.client.get(url).status_code,200)
    def test_admin_publishes_rate_and_rejects_invalid_range(self):
        from .models import FreightRate
        self.client.force_login(self.admin)
        today=timezone.localdate().isoformat()
        payload={'slug':'admin-rate','route':self.route.pk,'origin':'后台装货地','destination':'后台卸货地','vehicle':'整车','cargo':'普通货物','price_min':'100','price_max':'50','currency':'CNY','unit':'车','terms':'明确费用范围','source':'管理员核实','valid_from':today,'valid_until':today,'published':'on','_save':'保存'}
        response=self.client.post('/admin/web/freightrate/add/',payload)
        self.assertEqual(response.status_code,200)
        self.assertFalse(FreightRate.objects.filter(slug='admin-rate').exists())
        payload['price_max']='150'
        response=self.client.post('/admin/web/freightrate/add/',payload)
        self.assertEqual(response.status_code,302)
        rate=FreightRate.objects.get(slug='admin-rate')
        self.assertIsNotNone(rate.published_at)
        self.assertEqual(self.client.get(rate.get_absolute_url()).status_code,200)


from django.test import TransactionTestCase

class ResourceMigrationTests(TransactionTestCase):
    def test_existing_content_survives_upgrade(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        executor=MigrationExecutor(connection)
        try:
            executor.migrate([('web','0001_initial')])
            old=executor.loader.project_state([('web','0001_initial')]).apps
            article=old.get_model('web','Article').objects.create(title='升级前已有资料',slug='legacy-resource',kind='resources',category='原分类',summary='原摘要',body='管理员原文',published=False)
            executor=MigrationExecutor(connection)
            executor.migrate([('web','0003_resource_foundations')])
            upgraded=executor.loader.project_state([('web','0003_resource_foundations')]).apps
            saved=upgraded.get_model('web','Article').objects.get(pk=article.pk)
            self.assertEqual(saved.body,'管理员原文')
            self.assertFalse(saved.published)
            self.assertEqual(saved.category,'原分类')
            self.assertEqual(saved.resource_type.slug,'knowledge')
        finally:
            MigrationExecutor(connection).migrate([('web','0003_resource_foundations')])
