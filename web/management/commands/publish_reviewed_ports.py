"""Apply this edition to the exact 50 imported drafts, preserving other content."""
from datetime import date
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from web.models import Article, ArticleReference
from web.port_review import FIELDS, article_digest, catalog_digest


class Command(BaseCommand):
    help = '发布2026-11-07校订的50篇口岸草稿；先核验旧版本，拒绝覆盖管理员改稿或重新发布已撤下文章'

    def add_arguments(self, parser):
        parser.add_argument('--catalog',type=Path,default=settings.BASE_DIR/'content/ports/catalog.json')
        parser.add_argument('--revision',type=Path,default=settings.BASE_DIR/'content/ports/review-20261107.json')
        parser.add_argument('--dry-run',action='store_true',help='检查目标与版本，不改动数据库')

    def handle(self,*args,**options):
        try:
            catalog=json.loads(options['catalog'].read_text(encoding='utf-8'))
            revision=json.loads(options['revision'].read_text(encoding='utf-8'))
            entries={entry['slug']:entry for entry in catalog['entries']}
            targets=revision['entries']
            if revision['version']!=1 or len({e['slug'] for e in targets})!=len(targets):
                raise ValueError('Invalid revision version or duplicate target')
            for target in targets:
                entry=entries[target['slug']]
                if not entry['reviewed'] or not entry['references'] or not entry['body'].strip():
                    raise ValueError('Every target must contain reviewed content and sources')
                date.fromisoformat(entry['reviewed_on'])
                if catalog_digest(entry)!=target['after_sha256']:
                    raise ValueError('Reviewed catalog does not match the release manifest')
        except (OSError,KeyError,ValueError,TypeError) as exc:
            raise CommandError(f'Invalid port review release: {exc}') from exc

        changes=[]
        skipped=0
        with transaction.atomic():
            for target in targets:
                article=Article.objects.select_for_update().filter(slug=target['slug'],kind='resources',resource_type__slug='ports').first()
                if not article:
                    raise CommandError(f"Missing port {target['slug']}; run import_ports first.")
                fingerprint=article_digest(article)
                edition_date=date.fromisoformat(entries[article.slug]['reviewed_on'])
                if fingerprint==target['after_sha256'] or (article.reviewed_on and article.reviewed_on>=edition_date):
                    # Preserve this edition or a later administrator review, including unpublishing.
                    skipped+=1
                    continue
                if fingerprint!=target['before_sha256'] or article.published or article.published_at is not None:
                    raise CommandError(f"Port changed since review baseline: {article.slug}. No articles were updated; reconcile this record first.")
                changes.append((article,entries[article.slug]))
            if options['dry_run']:
                self.stdout.write(f'Validated {len(targets)} targets: {len(changes)} drafts to publish; {skipped} already edited. No changes made.')
                return
            for article,entry in changes:
                for field in FIELDS:
                    setattr(article,field,'markdown' if field=='body_format' else date.fromisoformat(entry[field]) if field=='reviewed_on' else entry[field])
                article.published=True
                article.published_at=timezone.now()
                article.full_clean()
                article.save(update_fields=[*FIELDS,'published','published_at','updated_at'])
                # Reference replacement is in the same transaction as the edited article.
                article.references.all().delete()
                for values in entry['references']:
                    reference=ArticleReference(article=article,**values)
                    reference.full_clean()
                    reference.save()
        self.stdout.write(self.style.SUCCESS(f'Edited and published {len(changes)} existing port drafts; unchanged {skipped}. Original manuscripts and media retained.'))
