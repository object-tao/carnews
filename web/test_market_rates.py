from decimal import Decimal
from io import StringIO
import json
from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from web.models import Article


@override_settings(SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['testserver','truck.diwuzhou.cn'], STORAGES={
    'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},
    'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class MarketReportTests(TestCase):
    def setUp(self):
        self.entry=json.loads((settings.BASE_DIR/'content/market-rates/2026-11-05.json').read_text(encoding='utf-8'))

    def load(self,**options):
        call_command('import_market_rates',stdout=StringIO(),**options)

    def test_totals_use_supplied_total_instead_of_recalculating_cost_components(self):
        rows={r['city']:r for r in self.entry['rows']}
        self.assertEqual(len(rows),21)
        self.assertEqual(sum(len(r['prices']) for r in rows.values()),210)
        self.assertEqual(Decimal(rows['阿拉木图']['prices'][0]),Decimal('5304')*Decimal('1.05'))
        # Supplied total is 7892, even though the separate cost cells would produce 7592.
        self.assertEqual(rows['阿斯塔纳']['prices'][2],'8286.60')
        self.assertEqual(rows['卡拉干达']['prices'][2],'8068.20')
        self.assertEqual(rows['杜尚别']['prices'][5],'13595.40')
        self.assertFalse(set(rows)&{'莫斯科','明斯克','圣彼得堡','叶卡捷琳堡'})
        self.assertIn('包含运费及境外转关费用',self.entry['body'])

    def test_public_placement_metadata_search_and_privacy(self):
        self.load(publish=True)
        item=Article.objects.get(slug=self.entry['slug'])
        self.assertEqual(item.original_source,'')
        self.assertEqual(item.countries.count(),3)
        listing=self.client.get('/prices/')
        self.assertContains(listing,item.title)
        self.assertNotContains(listing,'参考运价待发布')
        self.assertContains(self.client.get('/prices/?country=uzbekistan&q=塔什干'),item.title)
        self.assertNotContains(self.client.get('/prices/?country=belarus'),item.title)
        self.assertNotContains(self.client.get('/prices/?status=valid'),item.title)
        self.assertNotContains(self.client.get('/news/'),item.title)
        self.assertContains(self.client.get('/sitemap.xml'),item.get_absolute_url())
        response=self.client.get(item.get_absolute_url())
        self.assertContains(response,'<title>'+item.seo_title+' · 深圳昆腾</title>',html=True)
        self.assertContains(response,'name="keywords"')
        self.assertContains(response,'property="og:title"')
        self.assertContains(response,'href="/prices/"')
        html=response.content.decode()
        schema=json.loads(html.split('<script type="application/ld+json">')[1].split('</script>')[0])
        self.assertEqual(schema['headline'],item.title)
        self.assertEqual(schema['articleSection'],'参考运价')
        self.assertIn('霍尔果斯到中亚运价',schema['keywords'])
        for token in ['司机','税点','1.05','5%','source_total','莫斯科','明斯克']:
            self.assertNotIn(token,html)

    def test_drafts_scheduling_and_admin_edits_are_respected(self):
        self.load(dry_run=True)
        self.assertFalse(Article.objects.exists())
        self.load()
        item=Article.objects.get(slug=self.entry['slug'])
        self.assertEqual(self.client.get(item.get_absolute_url()).status_code,404)
        self.assertNotContains(self.client.get('/prices/'),item.title)
        item.body='ADMIN CONTENT'
        item.seo_title='ADMIN SEO'
        item.save()
        self.load(publish=True)
        item.refresh_from_db()
        self.assertFalse(item.published)
        self.assertEqual(item.body,'ADMIN CONTENT')
        self.assertEqual(item.seo_title,'ADMIN SEO')
        item.published=True
        item.published_at=timezone.now()+timedelta(days=1)
        item.save()
        self.assertNotContains(self.client.get('/prices/'),item.title)

    def test_keyword_markup_is_escaped_and_report_pagination_keeps_filters(self):
        self.load(publish=True)
        item=Article.objects.get(slug=self.entry['slug'])
        item.seo_title='Safe </title><script>alert(1)</script>'
        item.seo_keywords='主题,"/><script>alert(2)</script>'
        item.save()
        response=self.client.get(item.get_absolute_url())
        self.assertNotContains(response,'<script>alert(')
        for number in range(9):
            Article.objects.create(title='翻页运价',slug='report-'+str(number),kind='news',category='参考运价',summary='x',body='x',published=True,published_at=timezone.now())
        response=self.client.get('/prices/?status=reports')
        self.assertContains(response,'report_page=2')
        self.assertContains(response,'status=reports')
        response=self.client.get('/prices/?status=reports&report_page=2')
        self.assertEqual(len(response.context['report_page']),1)
