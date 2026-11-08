"""Import reviewed bridge/node articles; keep originals private and existing edits intact."""
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

from web.models import Article, ArticleReference, Country, ResourceType, Route
from .import_ports import contained_file


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Command(BaseCommand):
    help = '导入已校订桥涵节点文章及用户配图；不覆盖现有文章、图片、发布状态与管理员修改'

    def add_arguments(self, parser):
        parser.add_argument('--catalog', type=Path, default=settings.BASE_DIR / 'content/bridges/catalog.json')
        parser.add_argument('--original-dir', type=Path, help='可选的私有原稿目录，按SHA256校验后仅存入后台原始资料字段')
        parser.add_argument('--publish', action='store_true', help='仅发布本次新建的文章')
        parser.add_argument('--dry-run', action='store_true', help='核验资料、图片及原稿，不写入数据库或媒体')

    def handle(self, *args, **options):
        catalog = options['catalog'].resolve()
        try:
            bundle = json.loads(catalog.read_text(encoding='utf-8'))
            if bundle['version'] != 1:
                raise ValueError('Unsupported bridge catalog version')
            entries, names = bundle['entries'], bundle['countries']
            slugs, documents, pictures = set(), set(), set()
            for entry in entries:
                slug = entry['slug']
                if slug in slugs or not (slug == 'bridge-handbook' or slug == 'bridge-' + entry['id'] and entry['id'].isdigit()):
                    raise ValueError('Invalid or duplicate bridge slug')
                slugs.add(slug)
                if not entry['body'].strip() or not entry['source_files'] or not entry['references']:
                    raise ValueError('Body, source mapping and references are required')
                entry['_reviewed'] = date.fromisoformat(entry['reviewed_on'])
                if set(entry['countries']) - set(names):
                    raise ValueError('Country name mapping is missing')
                if set(entry['routes']) - {'central-asia', 'southeast-asia', 'russia-belarus', 'europe-uk'}:
                    raise ValueError('Unrecognized route identifier')
                entry['_original'] = ''
                notes = []
                for source in entry['source_files']:
                    if source['path'] in documents:
                        raise ValueError('Each original document must map to one article')
                    documents.add(source['path'])
                    notes.append(source['path'] + ' | SHA256: ' + source['sha256'])
                    if options['original_dir']:
                        path = contained_file(options['original_dir'], source['path'])
                        if checksum(path) != source['sha256']:
                            raise ValueError('Original document checksum mismatch: ' + source['path'])
                        entry['_original'] += '\n\n===== ' + source['path'] + ' =====\n\n' + path.read_text(encoding='utf-8-sig')
                photo = entry['photo']
                if photo['file'] in pictures or photo.get('kind') != 'ai_scene':
                    raise ValueError('Invalid or duplicate illustration mapping')
                pictures.add(photo['file'])
                for field in ('caption', 'note'):
                    if not all(label in photo[field] for label in ('AI生成', '非现场实拍')):
                        raise ValueError('AI illustrations need explicit disclosure')
                if photo.get('taken_on') or photo.get('source'):
                    raise ValueError('AI illustrations cannot claim a photographic source or date')
                if not photo['creator'] or len(photo['source_sha256']) != 64:
                    raise ValueError('Original image provenance missing')
                path = contained_file(catalog.parent, photo['file'])
                if checksum(path) != photo['sha256']:
                    raise ValueError('Display image checksum mismatch: ' + photo['file'])
                with Image.open(path) as image:
                    if image.format != 'WEBP' or list(image.size) != photo['dimensions']:
                        raise ValueError('Illustration format or dimensions differ from reviewed version')
                    image.verify()
                photo['_path'] = path
                entry['_notes'] = entry['editorial_notes'] + '\n\n原稿对应关系：\n' + '\n'.join(notes) + '\n原始配图：' + photo['source_file'] + ' | SHA256: ' + photo['source_sha256'] + '\n网页配图：' + photo['file'] + ' | SHA256: ' + photo['sha256']
            if len(documents) != bundle['source_document_count'] or len(pictures) != bundle['image_count']:
                raise ValueError('Source document or image coverage mismatch')
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise CommandError(f'Invalid bridge catalog: {exc}') from exc

        if options['dry_run']:
            self.stdout.write(f'Validated {len(entries)} articles, {len(documents)} source documents and {len(pictures)} images. No changes made.')
            return

        created, skipped = 0, 0
        saved, new_articles = [], []
        try:
            with transaction.atomic():
                resource_type, _ = ResourceType.objects.get_or_create(slug='bridges', defaults={'name': '桥梁介绍', 'order': 2})
                for entry in entries:
                    if Article.objects.filter(slug=entry['slug']).exists():
                        skipped += 1
                        continue
                    photo = entry['photo']
                    article = Article(
                        title=entry['title'], slug=entry['slug'], kind='resources', resource_type=resource_type,
                        category=entry['category'], location=entry['location'], summary=entry['summary'],
                        body=entry['body'], body_format='markdown', reviewed_on=entry['_reviewed'],
                        original_source=entry['_original'].lstrip(), editorial_notes=entry['_notes'],
                        image_caption=photo['caption'], image_note=photo['note'], image_creator=photo['creator'],
                        published=options['publish'], published_at=timezone.now() if options['publish'] else None,
                    )
                    article.full_clean()
                    article.save()
                    for slug in entry['countries']:
                        country, _ = Country.objects.get_or_create(slug=slug, defaults={'name': names[slug]})
                        article.countries.add(country)
                    for ref in entry['references']:
                        reference = ArticleReference(article=article, **ref)
                        reference.full_clean()
                        reference.save()
                    article.image.save(entry['slug'] + '.webp', ContentFile(photo['_path'].read_bytes()), save=False)
                    saved.append((article.image.storage, article.image.name))
                    article.save(update_fields=['image'])
                    article.related_routes.add(*Route.objects.filter(slug__in=entry['routes']))
                    new_articles.append((article, entry))
                    created += 1
                for article, entry in new_articles:
                    article.related_resources.add(*Article.objects.filter(slug__in=entry['related']))
        except Exception:
            for storage, name in saved:
                storage.delete(name)
            raise
        self.stdout.write(self.style.SUCCESS(f'Created {created}; published {created if options["publish"] else 0}; skipped existing {skipped}; images {len(pictures)}. Existing content preserved.'))
