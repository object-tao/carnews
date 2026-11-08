"""Replace only the known diagram edition with approved photos or labelled AI scenes."""
import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from web.models import Article
from web.port_images import IMAGE_METADATA_FIELDS, apply_port_image_metadata, port_image_metadata, validate_port_image


def matches_image(article, photo):
    if not article.image or any(getattr(article, key) != value for key, value in port_image_metadata(photo).items()):
        return False
    try:
        digest = hashlib.sha256()
        with article.image.open('rb') as source:
            for chunk in source.chunks():
                digest.update(chunk)
        return digest.hexdigest() == photo['sha256']
    except OSError:
        return False


class Command(BaseCommand):
    help = '将已确认的旧版口岸示意图升级为实拍或明确标注的AI场景图；保留管理员改图及文章内容'

    def add_arguments(self, parser):
        parser.add_argument('--catalog', type=Path, default=settings.BASE_DIR / 'content/ports/catalog.json')
        parser.add_argument('--edition', type=Path, default=settings.BASE_DIR / 'content/ports/scene-upgrade-20261107.json')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        try:
            catalog = json.loads(options['catalog'].read_text(encoding='utf-8'))
            edition = json.loads(options['edition'].read_text(encoding='utf-8'))
            entries = {entry['slug']: entry for entry in catalog['entries']}
            targets = edition['entries']
            if edition['version'] != 1 or len({target['slug'] for target in targets}) != len(targets):
                raise ValueError('Invalid visual edition version or duplicate target')
            prepared = []
            for target in targets:
                entry = entries[target['slug']]
                before, after = target['before'], target['after']
                if target['id'] != entry['id'] or entry['slug'] != 'port-' + entry['id']:
                    raise ValueError('Visual edition port identifier mismatch')
                if after != entry['photo'] or before.get('kind') != 'diagram' or after.get('kind') not in ('photo', 'ai_scene'):
                    raise ValueError('Only the approved diagram-to-photo/scene transition is supported')
                if not before.get('sha256') or not after.get('sha256'):
                    raise ValueError('Both image versions need checksums')
                validate_port_image(before, options['catalog'].parent)
                path = validate_port_image(after, options['catalog'].parent)
                prepared.append((entry['slug'], before, after, path))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CommandError(f'Invalid port visual upgrade: {exc}') from exc

        changes = []
        saved_files = []
        current = preserved = 0
        try:
            with transaction.atomic():
                for slug, before, after, path in prepared:
                    article = Article.objects.select_for_update().filter(slug=slug, kind='resources', resource_type__slug='ports').first()
                    if not article:
                        preserved += 1
                        continue
                    if matches_image(article, after):
                        current += 1
                        continue
                    if not matches_image(article, before):
                        preserved += 1
                        continue
                    apply_port_image_metadata(article, after)
                    article.full_clean()
                    changes.append((article, path))
                if options['dry_run']:
                    self.stdout.write(f'Validated {len(prepared)} targets; would replace {len(changes)}; current {current}; preserve administrator changes {preserved}. No changes made.')
                    return
                for article, path in changes:
                    article.image.save(article.slug + '-visual-20261107' + path.suffix.lower(), ContentFile(path.read_bytes()), save=False)
                    saved_files.append((article.image.storage, article.image.name))
                    article.save(update_fields=['image', *IMAGE_METADATA_FIELDS, 'updated_at'])
        except Exception:
            for storage, name in saved_files:
                storage.delete(name)
            raise
        self.stdout.write(self.style.SUCCESS(f'Replaced {len(changes)} port diagrams; current {current}; preserved administrator changes {preserved}. Original media retained; article content unchanged.'))
