"""Import the edited heavy-haul collection without overwriting administrator edits."""
from datetime import date
import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from web.models import Article, ArticleReference, Country, ResourceType
from .import_ports import contained_file

COUNTRY_NAMES = {'china':'中国','kazakhstan':'哈萨克斯坦','kyrgyzstan':'吉尔吉斯斯坦',
    'uzbekistan':'乌兹别克斯坦','tajikistan':'塔吉克斯坦','russia':'俄罗斯',
    'belarus':'白俄罗斯','mongolia':'蒙古国','united-kingdom':'英国'}

class Command(BaseCommand):
    help = '导入重写后的大件运输专题；原稿可选存入后台，不覆盖现有文章及管理员修改'

    def add_arguments(self, parser):
        parser.add_argument('--catalog', type=Path, default=settings.BASE_DIR/'content/knowledge/catalog.json')
        parser.add_argument('--original-dir', type=Path, help='原始知识库目录；校验文件摘要后，仅将原文存入后台')
        parser.add_argument('--publish', action='store_true', help='发布本次新建的已编辑专题，不更改已有文章状态')
        parser.add_argument('--dry-run', action='store_true', help='核验文件与索引，不写数据库')

    def handle(self, *args, **options):
        originals = {}
        try:
            bundle = json.loads(options['catalog'].read_text(encoding='utf-8'))
            if bundle.get('version') != 1:
                raise ValueError('Unsupported catalog version')
            entries = bundle['entries']
            slugs = set()
            source_paths = set()
            for item in entries:
                slug = item['slug']
                if not slug.startswith('heavy-haul-') or slug in slugs:
                    raise ValueError('Duplicate or invalid article slug')
                slugs.add(slug)
                if not item['body'].strip() or not item['source_files']:
                    raise ValueError('Body and original-document index are required')
                item['_reviewed'] = date.fromisoformat(item['reviewed_on'])
                item['_original'] = ''
                source_notes = []
                for source in item['source_files']:
                    path = source['path']
                    source_paths.add(path)
                    source_notes.append(f"{source['id']} | {path} | SHA256: {source['sha256']}")
                    if options['original_dir']:
                        if path not in originals:
                            raw = contained_file(options['original_dir'], path).read_bytes()
                            if hashlib.sha256(raw).hexdigest() != source['sha256']:
                                raise CommandError(f'Original file changed since editorial review: {path}')
                            originals[path] = raw.decode('utf-8-sig')
                        item['_original'] += f'\n\n===== {path} =====\n\n' + originals[path]
                item['_notes'] = item['editorial_notes'] + '\n\n原稿对应关系：\n' + '\n'.join(source_notes)
            if len(source_paths) != bundle['source_document_count']:
                raise ValueError('Original-document coverage does not match the catalog')
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise CommandError(f'Invalid knowledge catalog: {exc}') from exc

        if options['dry_run']:
            self.stdout.write(f'Validated {len(entries)} articles covering {len(source_paths)} source files. No changes made.')
            return

        created = skipped = 0
        new_articles = []
        with transaction.atomic():
            resource_type, _ = ResourceType.objects.get_or_create(slug='knowledge', defaults={'name':'运输知识','order':3})
            for item in entries:
                if Article.objects.filter(slug=item['slug']).exists():
                    skipped += 1
                    continue
                article = Article(
                    title=item['title'], slug=item['slug'], kind='resources', category=item['category'],
                    resource_type=resource_type, summary=item['summary'], body=item['body'], body_format='markdown',
                    reviewed_on=item['_reviewed'], original_source=item['_original'].lstrip(), editorial_notes=item['_notes'],
                    published=options['publish'], published_at=timezone.now() if options['publish'] else None,
                )
                article.full_clean()
                article.save()
                for slug in item['countries']:
                    if slug not in COUNTRY_NAMES:
                        raise CommandError(f'Unrecognized country: {slug}')
                    country, _ = Country.objects.get_or_create(slug=slug, defaults={'name':COUNTRY_NAMES[slug]})
                    article.countries.add(country)
                for ref in item['references']:
                    reference = ArticleReference(article=article, **ref)
                    reference.full_clean()
                    reference.save()
                new_articles.append((article,item))
                created += 1
            for article,item in new_articles:
                related = Article.objects.filter(slug__in=item['related'])
                article.related_resources.add(*related)
        self.stdout.write(self.style.SUCCESS(f'Created {created}; published {created if options["publish"] else 0}; skipped existing {skipped}; covered source files {len(source_paths)}.'))
