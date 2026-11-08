"""Import dated market reports without exposing the input cost breakdown."""
from datetime import date
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from web.models import Article, Country, Route


class Command(BaseCommand):
    help = '导入市场运价文章；原始费用明细不入库，保留已有文章及管理员编辑'

    def add_arguments(self, parser):
        parser.add_argument('--catalog',type=Path,default=settings.BASE_DIR/'content/market-rates/2026-11-05.json')
        parser.add_argument('--publish',action='store_true')
        parser.add_argument('--dry-run',action='store_true')

    def handle(self,*args,**options):
        try:
            entry=json.loads(options['catalog'].read_text(encoding='utf-8'))
            quote_date=date.fromisoformat(entry['quote_date'])
            if entry['currency'] != 'USD' or entry['origin'] != '新疆霍尔果斯':
                raise ValueError('Unconfirmed currency or origin')
            if len(entry['rows']) != 21 or len(entry['vehicles']) != 10 or len({r['city'] for r in entry['rows']}) != 21:
                raise ValueError('City or vehicle coverage mismatch')
            for row in entry['rows']:
                if row['country'] not in entry['countries'].values() or len(row['prices']) != 10:
                    raise ValueError('Incomplete country or vehicle row')
                for value in row['prices']:
                    price=Decimal(value)
                    if not price.is_finite() or price <= 0 or price.as_tuple().exponent != -2:
                        raise ValueError('Invalid published price')
                    if f'{price:,.2f}' not in entry['body']:
                        raise ValueError('Published price missing from article')
            if any(word in entry['body'] for word in ['司机','税点','1.05','5%','source_total','莫斯科','明斯克','圣彼得堡','叶卡捷琳堡']):
                raise ValueError('Internal breakdown or excluded city in article')
            article=Article(title=entry['title'],slug=entry['slug'],kind='news',category='参考运价',quote_date=quote_date,summary=entry['summary'],body=entry['body'],body_format='markdown',seo_title=entry['seo_title'],seo_keywords=entry['seo_keywords'],editorial_notes=entry['editorial_notes'])
            article.full_clean(validate_unique=False)
        except (OSError,KeyError,TypeError,ValueError,InvalidOperation) as exc:
            raise CommandError(f'Invalid market report: {exc}') from exc
        if options['dry_run']:
            self.stdout.write('Validated 21 cities and 210 published totals. No changes made.')
            return
        with transaction.atomic():
            if Article.objects.filter(slug=entry['slug']).exists():
                self.stdout.write('Skipped existing market report; administrator edits preserved.')
                return
            article.published=options['publish']
            article.published_at=timezone.now() if options['publish'] else None
            article.save()
            for slug,name in entry['countries'].items():
                country,_=Country.objects.get_or_create(slug=slug,defaults={'name':name})
                article.countries.add(country)
            article.related_routes.add(*Route.objects.filter(slug='central-asia'))
        self.stdout.write(self.style.SUCCESS('Created 1 market report with 210 totals; published: '+str(options['publish'])))
