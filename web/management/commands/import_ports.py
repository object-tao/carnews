"""Repeatable port import; existing administrator edits are never overwritten."""
import json
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from PIL import Image

from web.models import Article, ArticleReference, Country, ResourceType, Route


def contained_file(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise CommandError(f'File missing or outside the selected directory: {relative}')
    return path


class Command(BaseCommand):
    help = '导入口岸资料；已存在记录保留管理员修改，未核实稿件始终作为草稿导入'

    def add_arguments(self, parser):
        parser.add_argument('--catalog', type=Path, default=settings.BASE_DIR / 'content/ports/catalog.json')
        parser.add_argument('--original-dir', type=Path, help='可选：原始Markdown目录，完整原文仅存入后台字段')
        parser.add_argument('--publish-reviewed', action='store_true', help='仅将本次新建且已校订的资料公开')
        parser.add_argument('--dry-run', action='store_true', help='验证资料及图片，不修改数据库或媒体文件')

    def handle(self, *args, **options):
        catalog = options['catalog'].resolve()
        try:
            bundle = json.loads(catalog.read_text(encoding='utf-8'))
            entries = bundle['entries']
            if bundle.get('version') != 1 or not isinstance(entries, list):
                raise ValueError('Unsupported catalog format')
            slugs = set()
            for item in entries:
                if item['slug'] != 'port-' + item['id'] or item['slug'] in slugs:
                    raise ValueError('Invalid or duplicate port identifier')
                slugs.add(item['slug'])
                if type(item['reviewed']) is not bool:
                    raise ValueError('Review flag must be boolean')
                if item['reviewed'] and (not item['references'] or not item['reviewed_on']):
                    raise ValueError('Reviewed profiles require sources and a review date')
                item['_date'] = date.fromisoformat(item['reviewed_on']) if item['reviewed_on'] else None
                item['_original'] = ''
                if options['original_dir']:
                    item['_original'] = contained_file(options['original_dir'], item['source_file']).read_text(encoding='utf-8-sig')
                if item.get('photo'):
                    photo = item['photo']
                    if not all(photo.get(k) for k in ('creator', 'source', 'license', 'license_url', 'caption')):
                        raise ValueError('Photo attribution is incomplete')
                    photo['_path'] = contained_file(catalog.parent, photo['file'])
                    with Image.open(photo['_path']) as image:
                        image.verify()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CommandError(f'Invalid port catalog: {exc}') from exc

        reviewed = sum(item['reviewed'] for item in entries)
        if options['dry_run']:
            self.stdout.write(f'Validated {len(entries)} profiles: {reviewed} reviewed, {len(entries)-reviewed} drafts. No changes made.')
            return

        created = skipped = published = 0
        saved_files = []
        try:
            with transaction.atomic():
                resource_type, _ = ResourceType.objects.get_or_create(slug='ports', defaults={'name':'口岸介绍','order':0})
                china, _ = Country.objects.get_or_create(slug='china', defaults={'name':'中国','order':0})
                for item in entries:
                    if Article.objects.filter(slug=item['slug']).exists():
                        skipped += 1
                        continue
                    is_public = item['reviewed'] and options['publish_reviewed']
                    article = Article(
                        slug=item['slug'], title=item['title'], kind='resources', category='口岸介绍',
                        resource_type=resource_type, location=item['location'], summary=item['summary'],
                        body=item['body'], body_format='markdown', reviewed_on=item['_date'],
                        original_source=item['_original'], editorial_notes=item['editorial_notes'],
                        published=is_public, published_at=timezone.now() if is_public else None,
                    )
                    photo = item.get('photo')
                    if photo:
                        article.image_caption = photo['caption']
                        article.image_note = '历史实景资料图，不代表当前设施或通关状态；使用 Commons 缩略版本，未改动图像内容。'
                        article.image_creator = photo['creator']
                        article.image_source = photo['source']
                        article.image_license = photo['license']
                        article.image_license_url = photo['license_url']
                        article.image_taken_on = photo['taken_on']
                    article.full_clean()
                    article.save()
                    country, _ = Country.objects.get_or_create(slug=item['country']['slug'], defaults={'name':item['country']['name']})
                    article.countries.add(china, country)
                    if item.get('route'):
                        route = Route.objects.filter(slug=item['route']).first()
                        if route:
                            article.related_routes.add(route)
                    for source in item['references']:
                        reference = ArticleReference(article=article, **source)
                        reference.full_clean()
                        reference.save()
                    if photo:
                        article.image.save(item['slug']+'.jpg', ContentFile(photo['_path'].read_bytes()), save=False)
                        saved_files.append((article.image.storage, article.image.name))
                        article.save(update_fields=['image'])
                    created += 1
                    published += bool(is_public)
        except Exception:
            # Only clean up files created by this invocation after the DB transaction rolls back.
            for storage, name in saved_files:
                storage.delete(name)
            raise
        self.stdout.write(self.style.SUCCESS(f'Created {created}; published {published}; drafts {created-published}; skipped existing {skipped}.'))
