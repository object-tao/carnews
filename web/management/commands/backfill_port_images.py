"""Fill this edition's empty images without changing editorial content."""
import json
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from web.models import Article
from web.port_images import IMAGE_METADATA_FIELDS, apply_port_image_metadata, validate_port_image


class Command(BaseCommand):
    help = '为2026-11-07图片版补齐空白口岸配图；保留已有图片、管理员图片说明、正文和发布状态'

    def add_arguments(self, parser):
        parser.add_argument('--catalog', type=Path, default=settings.BASE_DIR / 'content/ports/catalog.json')
        parser.add_argument('--edition', type=Path, default=settings.BASE_DIR / 'content/ports/image-edition-20261107.json')
        parser.add_argument('--dry-run', action='store_true', help='验证图片和变更范围，不写入数据库或文件')

    def handle(self, *args, **options):
        try:
            catalog = json.loads(options['catalog'].read_text(encoding='utf-8'))
            edition = json.loads(options['edition'].read_text(encoding='utf-8'))
            entries = {entry['slug']: entry for entry in catalog['entries']}
            targets = edition['entries']
            if catalog['version'] != 1 or edition['version'] != 1 or len({entry['slug'] for entry in targets}) != len(targets):
                raise ValueError('Invalid image edition version or duplicate target')
            prepared = []
            for target in targets:
                entry = entries[target['slug']]
                # This is a historical, self-contained edition. Later visual
                # upgrades may legitimately point the current catalog elsewhere.
                photo = target
                if entry['slug'] != 'port-' + entry['id'] or target['id'] != entry['id']:
                    raise ValueError('Image edition port identifier mismatch')
                if not photo.get('sha256'):
                    raise ValueError('Image edition requires a file checksum')
                path = validate_port_image(photo, options['catalog'].parent)
                prepared.append((entry['slug'], photo, path))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CommandError(f'Invalid port image edition: {exc}') from exc

        saved_files = []
        changes = []
        skipped = 0
        try:
            with transaction.atomic():
                for slug, photo, path in prepared:
                    article = Article.objects.select_for_update().filter(
                        slug=slug, kind='resources', resource_type__slug='ports',
                    ).first()
                    # Nonempty credits may be an administrator's work in progress,
                    # or a photo deliberately removed while retaining its metadata.
                    if not article or article.image or any(getattr(article, field) for field in IMAGE_METADATA_FIELDS):
                        skipped += 1
                        continue
                    apply_port_image_metadata(article, photo)
                    article.full_clean()
                    changes.append((article, path))
                if options['dry_run']:
                    self.stdout.write(f'Validated {len(prepared)} images; would fill {len(changes)}; preserve {skipped}. No changes made.')
                    return
                for article, path in changes:
                    article.image.save(article.slug + path.suffix.lower(), ContentFile(path.read_bytes()), save=False)
                    saved_files.append((article.image.storage, article.image.name))
                    article.save(update_fields=['image', *IMAGE_METADATA_FIELDS, 'updated_at'])
        except Exception:
            for storage, name in saved_files:
                storage.delete(name)
            raise
        self.stdout.write(self.style.SUCCESS(f'Filled {len(changes)} empty port images; preserved {skipped}. Editorial content and publication states unchanged.'))
