from decimal import Decimal
from io import StringIO
import json
from datetime import date, timedelta

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
        self.assertEqual(item.quote_date,date(2026,11,4))
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

    def test_quote_date_orders_all_pages_and_filters_despite_reverse_import_order(self):
        from web.models import Country
        country,_=Country.objects.get_or_create(slug='kazakhstan',defaults={'name':'哈萨克斯坦'})
        now=timezone.now()
        dates=[date(2026,11,4),date(2026,11,2),*[date(2026,10,day) for day in [30,27,24,22,19,15,13,12,10,8,6,4]]]
        expected=[]
        for number,quote_date in enumerate(dates):
            article=Article.objects.create(title='霍尔果斯报价 '+str(quote_date),slug='dated-'+str(number),kind='news',category='参考运价',summary='霍尔果斯',body='x',quote_date=quote_date,published=True,published_at=now-timedelta(days=14-number))
            article.countries.add(country)
            expected.append(article.pk)
        undated=Article.objects.create(title='日期待补',slug='undated',kind='news',category='参考运价',summary='霍尔果斯',body='x',published=True,published_at=now)
        undated.countries.add(country)
        expected.append(undated.pk)
        Article.objects.create(title='未来发布',slug='scheduled-report',kind='news',category='参考运价',summary='霍尔果斯',body='x',quote_date=date(2026,12,1),published=True,published_at=now+timedelta(days=1))
        for query in ['', 'status=reports&country=kazakhstan&q=霍尔果斯']:
            first=self.client.get('/prices/?'+query)
            second=self.client.get('/prices/?'+query+'&report_page=2')
            actual=[item.pk for response in [first,second] for item in response.context['report_page']]
            self.assertEqual(actual,expected)
            self.assertContains(first,'<time datetime="2026-11-04">报价 2026.11.04</time>',html=True)
            self.assertContains(second,'报价日期待补充')
            self.assertNotContains(first,'未来发布')
        detail=self.client.get('/articles/dated-0/')
        self.assertContains(detail,'报价日期 2026-11-04')
        schema=json.loads(detail.content.decode().split('<script type="application/ld+json">')[1].split('</script>')[0])
        self.assertEqual(schema['datePublished'],(now-timedelta(days=14)).isoformat())

    def test_date_backfill_corrects_confirmed_report_without_changing_prices_or_other_news(self):
        import importlib
        from django.apps import apps
        from django.db import connection
        migration=importlib.import_module('web.migrations.0009_article_quote_date')
        old=Article.objects.create(title='霍尔果斯至中亚整车参考运价（2026年11月5日）',slug=self.entry['slug'],kind='news',category='参考运价',summary='2026年11月5日',seo_title='报价2026-11-05',body='日期2026年11月5日\n| 阿拉木图 | 5,569.20 |',published_at=timezone.now())
        historical=Article.objects.create(title='历史报价（2026年10月4日）',slug='old-quote',kind='news',category='参考运价',summary='x',body='unaltered')
        news=Article.objects.create(title='行业新闻（2026年11月5日）',slug='normal-news',kind='news',category='行业新闻',summary='x',body='x')
        published_at=old.published_at
        migration.backfill_quote_dates(apps,connection.schema_editor())
        old.refresh_from_db(); historical.refresh_from_db(); news.refresh_from_db()
        self.assertEqual(old.quote_date,date(2026,11,4))
        self.assertEqual(old.published_at,published_at)
        self.assertIn('2026年11月4日',old.title)
        self.assertIn('| 阿拉木图 | 5,569.20 |',old.body)
        self.assertEqual(old.slug,self.entry['slug'])
        self.assertEqual(historical.quote_date,date(2026,10,4))
        self.assertEqual(historical.body,'unaltered')
        self.assertIsNone(news.quote_date)
