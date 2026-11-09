from django.core.management.base import BaseCommand
from cgr.catalog import CATALOG
from cgr.models import Checkpoint, CollectorSettings
from web.models import Article


class Command(BaseCommand):
    help = 'Initialize the verified CGR checkpoint catalog without overwriting admin edits.'

    def handle(self, *args, **options):
        CollectorSettings.objects.get_or_create(pk=1)
        added = 0
        for country, source_name, name, _ in CATALOG:
            obj, created = Checkpoint.objects.get_or_create(source_name=source_name, defaults={
                'name': name, 'country': country, 'node_type': 'port' if country == 'xa' else 'land'})
            added += int(created)
            if not obj.article_id and country == 'cn':
                matches = Article.objects.filter(kind='resources', resource_type__slug='ports', title__icontains=name.split('—')[0])
                if matches.count() == 1:
                    obj.article = matches.first()
                    obj.save(update_fields=['article'])
        self.stdout.write(f'CGR catalog: {Checkpoint.objects.count()} nodes, {added} added.')
