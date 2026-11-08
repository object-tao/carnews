from datetime import date
import re

from django.db import migrations, models
from django.utils import timezone


def backfill_quote_dates(apps, schema_editor):
    Article = apps.get_model('web', 'Article')
    articles = Article.objects.using(schema_editor.connection.alias).filter(kind='news', category='参考运价')
    for article in articles.iterator():
        match = re.search(r'[（(](\d{4})年(\d{1,2})月(\d{1,2})日[）)]$', article.title)
        if not match:
            continue
        try:
            quote_date = date(*map(int, match.groups()))
        except ValueError:
            continue
        changes = {'quote_date': quote_date}
        # User corrected this report's quotation date. Preserve its existing URL and all prices.
        if article.slug == 'khorgos-central-asia-freight-rates-2026-11-05' and quote_date == date(2026, 11, 5):
            changes['quote_date'] = date(2026, 11, 4)
            for field in ['title', 'summary', 'body', 'seo_title', 'editorial_notes']:
                changes[field] = getattr(article, field).replace('2026年11月5日', '2026年11月4日').replace('2026-11-05', '2026-11-04')
            changes['updated_at'] = timezone.now()
        articles.filter(pk=article.pk).update(**changes)


class Migration(migrations.Migration):
    dependencies = [('web', '0008_article_seo_keywords_article_seo_title')]
    operations = [
        migrations.AddField(
            model_name='article', name='quote_date',
            field=models.DateField('报价日期', null=True, blank=True, help_text='参考运价文章对应的市场报价日期，用于列表显示和排序，与实际发布时间分开。'),
        ),
        migrations.RunPython(backfill_quote_dates, migrations.RunPython.noop),
    ]
