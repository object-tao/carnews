"""Import edited vehicle profiles and the user's unchanged illustrations."""
from datetime import date
import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from PIL import Image

from web.models import Article, ArticleReference, ResourceType
from .import_ports import contained_file


class Command(BaseCommand):
    help = '导入车型文章及配图；默认草稿，重复运行保留现有文章、图片与管理员修改'

    def add_arguments(self, parser):
        parser.add_argument('--catalog', type=Path, default=settings.BASE_DIR/'content/vehicles/catalog.json')
        parser.add_argument('--original-dir', type=Path, help='可选：原始车型目录，核验摘要后将原稿存入后台')
        parser.add_argument('--publish', action='store_true', help='仅发布本次新建的已编辑文章')
        parser.add_argument('--dry-run', action='store_true', help='核验文章、索引与图片，不修改数据库及媒体')

    def handle(self, *args, **options):
        catalog = options['catalog'].resolve()
        try:
            bundle = json.loads(catalog.read_text(encoding='utf-8'))
            if bundle['version'] != 1:
                raise ValueError('Unsupported catalog version')
            entries = bundle['entries']
            slugs, originals, photos = set(), set(), set()
            for item in entries:
                if not item['slug'].startswith('vehicle-') or item['slug'] in slugs:
                    raise ValueError('Invalid or duplicate vehicle slug')
                slugs.add(item['slug'])
                if not item['body'].strip() or not item['references'] or not item['source_files']:
                    raise ValueError('Body, references and source files are required')
                item['_date'] = date.fromisoformat(item['reviewed_on'])
                item['_original'] = ''
                notes = []
                for source in item['source_files']:
                    originals.add(source['path'])
                    notes.append(f"{source['path']} | SHA256: {source['sha256']}")
                    if options['original_dir']:
                        raw = contained_file(options['original_dir'], source['path']).read_bytes()
                        if hashlib.sha256(raw).hexdigest() != source['sha256']:
                            raise ValueError(f"Original file changed: {source['path']}")
                        item['_original'] += f"\n\n===== {source['path']} =====\n\n" + raw.decode('utf-8-sig')
                item['_notes'] = item['editorial_notes'] + '\n\n原始资料索引：\n' + '\n'.join(notes)
                if item.get('photo'):
                    photo = item['photo']
                    if photo['file'] in photos or not photo['caption'] or 'AI' not in photo['note']:
                        raise ValueError('Image mapping or AI provenance is missing')
                    photos.add(photo['file'])
                    photo['_path'] = contained_file(catalog.parent, photo['file'])
                    raw = photo['_path'].read_bytes()
                    if hashlib.sha256(raw).hexdigest() != photo['sha256']:
                        raise ValueError(f"Image checksum mismatch: {photo['file']}")
                    with Image.open(photo['_path']) as image:
                        if image.format != 'PNG':
                            raise ValueError('Expected unchanged PNG source image')
                        image.verify()
                    if options['original_dir']:
                        original = contained_file(options['original_dir'], photo['source_file']).read_bytes()
                        if original != raw:
                            raise ValueError('Packaged image differs from the supplied original')
                    item['_notes'] += f"\n原图：{photo['source_file']} | SHA256: {photo['sha256']}；原样保留。"
            if len(originals) != bundle['source_document_count'] or len(photos) != bundle['image_count']:
                raise ValueError('Source or image coverage does not match catalog')
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise CommandError(f'Invalid vehicle catalog: {exc}') from exc

        if options['dry_run']:
            self.stdout.write(f'Validated {len(entries)} articles, {len(photos)} images and {len(originals)} source documents. No changes made.')
            return

        created = skipped = 0
        saved_files, new_articles = [], []
        try:
            with transaction.atomic():
                resource_type, _ = ResourceType.objects.get_or_create(slug='vehicles', defaults={'name':'车型介绍','order':1})
                for item in entries:
                    if Article.objects.filter(slug=item['slug']).exists():
                        skipped += 1
                        continue
                    article = Article(
                        title=item['title'], slug=item['slug'], kind='resources', category=item['category'],
                        resource_type=resource_type, summary=item['summary'], body=item['body'], body_format='markdown',
                        reviewed_on=item['_date'], original_source=item['_original'].lstrip(), editorial_notes=item['_notes'],
                        published=options['publish'], published_at=timezone.now() if options['publish'] else None,
                    )
                    photo = item.get('photo')
                    if photo:
                        article.image_caption = photo['caption']
                        article.image_creator = '用户提供的车型资料'
                        article.image_note = photo['note']
                    article.full_clean()
                    article.save()
                    for ref in item['references']:
                        reference = ArticleReference(article=article, **ref)
                        reference.full_clean()
                        reference.save()
                    if photo:
                        article.image.save(item['slug']+'.png', ContentFile(photo['_path'].read_bytes()), save=False)
                        saved_files.append((article.image.storage, article.image.name))
                        article.save(update_fields=['image'])
                    new_articles.append((article, item))
                    created += 1
                for article, item in new_articles:
                    article.related_resources.add(*Article.objects.filter(slug__in=item['related']))
        except Exception:
            for storage, name in saved_files:
                storage.delete(name)
            raise
        self.stdout.write(self.style.SUCCESS(f'Created {created}; published {created if options["publish"] else 0}; skipped existing {skipped}; images in catalog {len(photos)}.'))
