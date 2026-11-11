from django.core.management.base import BaseCommand, CommandError
from horgos.service import collect


class Command(BaseCommand):
    help = '采集霍尔果斯当日数据；--scheduled 按北京时间任务设置执行。'
    def add_arguments(self, parser): parser.add_argument('--scheduled', action='store_true')
    def handle(self, *args, **options):
        run = collect(scheduled=options['scheduled'])
        if run is None: return
        if run.status != 'success': raise CommandError(f'Horgos #{run.pk}: {run.message}')
        self.stdout.write(f'Horgos #{run.pk}: {run.message}')
