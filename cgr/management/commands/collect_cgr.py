from django.core.management.base import BaseCommand, CommandError
from cgr.service import collect


class Command(BaseCommand):
    help = 'Collect CGR once, or poll the configured daily schedule and manual requests.'

    def add_arguments(self, parser):
        parser.add_argument('--scheduled', action='store_true')

    def handle(self, *args, **options):
        run = collect(scheduled=options['scheduled'])
        if run is None:
            return
        if run.status != 'success':
            raise CommandError(f'CGR #{run.pk}: {run.message}')
        self.stdout.write(f'CGR #{run.pk}: {run.message}')
