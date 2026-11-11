from django.core.management.base import BaseCommand
from django.db import transaction
from cgr.models import DailyReport
from cgr.service import publish_report
from horgos.models import Settings, Report
from horgos.service import report_title
from horgos.client import SOURCE_URL


class Command(BaseCommand):
    help = '更新旧口岸日报为公开汇总口径，并初始化霍尔果斯任务设置；不联网采集。'
    def handle(self, *args, **options):
        Settings.objects.get_or_create(pk=1)
        count = 0
        renamed = 0
        source_updated = 0
        with transaction.atomic():
            for report in DailyReport.objects.select_related('article', 'run'):
                if 'CSV明细' in report.article.summary:
                    publish_report(report.run, auto_publish=report.article.published)
                    count += 1
            for report in Report.objects.select_related('article'):
                title = report_title(report.date)
                article = report.article
                if article.title != title or article.seo_title != title:
                    article.title = article.seo_title = title
                    article.save(update_fields=['title', 'seo_title', 'updated_at'])
                    renamed += 1
                body = article.body.replace(f'数据来源：[霍尔果斯口岸数据接口]({SOURCE_URL}/postNumNow)。', '数据来源：中国电子口岸。')
                if body != article.body:
                    article.body = body
                    article.save(update_fields=['body', 'updated_at'])
                    source_updated += 1
        self.stdout.write(f'已转换 {count} 篇历史口岸汇总文章。')
        self.stdout.write(f'已更新 {renamed} 篇霍尔果斯放行报告标题。')
        self.stdout.write(f'已更新 {source_updated} 篇霍尔果斯报告的来源署名。')
