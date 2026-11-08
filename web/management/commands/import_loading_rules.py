"""Import reviewed loading articles into the independent 大件知识 resource type."""
from datetime import date
import hashlib
import json
from pathlib import Path
import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from web.models import Article, ArticleReference, Country, ResourceType, Route
from .import_ports import contained_file


class Command(BaseCommand):
    help = '导入大件知识配载专题；保留已有文章和管理员编辑，原始规则资料仅存后台'

    def add_arguments(self, parser):
        parser.add_argument('--catalog', type=Path, default=settings.BASE_DIR / 'content/heavy-cargo/catalog.json')
        parser.add_argument('--original-dir', type=Path, help='可选的私有原稿目录，按SHA256校验')
        parser.add_argument('--publish', action='store_true', help='仅发布本次新建文章，不发布已有草稿')
        parser.add_argument('--dry-run', action='store_true', help='核验数据与来源，不写入数据库')

    def handle(self, *args, **options):
        try:
            bundle = json.loads(options['catalog'].read_text(encoding='utf-8'))
            if bundle['version'] != 1:
                raise ValueError('Unsupported loading catalog version')
            entries, names = bundle['entries'], bundle['countries']
            slugs, identifiers, documents = set(), set(), set()
            for entry in entries:
                slug, identifier = entry['slug'], entry['id']
                if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug) or slug in slugs or identifier in identifiers:
                    raise ValueError('Invalid or duplicate article identifier')
                slugs.add(slug)
                identifiers.add(identifier)
                if not entry['body'].strip() or not entry['source_files']:
                    raise ValueError('Body and source mapping are required')
                if set(entry['countries']) - set(names):
                    raise ValueError('Country name mapping is missing')
                if set(entry['routes']) - {'central-asia', 'russia-belarus'}:
                    raise ValueError('Unknown route')
                entry['_reviewed'] = date.fromisoformat(entry['reviewed_on'])
                entry['_original'] = ''
                notes = []
                for source in entry['source_files']:
                    if source['path'] in documents or not re.fullmatch('[0-9a-f]{64}', source['sha256']):
                        raise ValueError('Duplicate source mapping or invalid checksum')
                    documents.add(source['path'])
                    notes.append(source['path'] + ' | SHA256: ' + source['sha256'])
                    if options['original_dir']:
                        raw = contained_file(options['original_dir'], source['path']).read_bytes()
                        if hashlib.sha256(raw).hexdigest() != source['sha256']:
                            raise ValueError('Original document checksum mismatch: ' + source['path'])
                        entry['_original'] += '\n\n===== ' + source['path'] + ' =====\n\n' + raw.decode('utf-8-sig')
                entry['_notes'] = entry['editorial_notes'] + '\n\n原稿对应关系：\n' + '\n'.join(notes)
            if len(documents) != bundle['source_document_count'] or len(entries) != bundle['rule_article_count'] + 1:
                raise ValueError('Source or rule coverage mismatch')
            for entry in entries:
                for url in re.findall(r'\]\((/articles/[^)]+)\)', entry['body']):
                    if url.strip('/').split('/')[-1] not in slugs | {'heavy-haul-handbook','vehicle-handbook','bridge-handbook'}:
                        raise ValueError('Unmapped internal article link: ' + url)
                if re.search(r'\]\([^)]*\.md\)|admin\.ostoa|source_rule_|loading_rules|前端资源', entry['body']):
                    raise ValueError('Internal source data or unresolved Markdown link in public body')
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise CommandError(f'Invalid loading catalog: {exc}') from exc

        if options['dry_run']:
            self.stdout.write(f'Validated {len(entries)} articles and {len(documents)} source documents. No changes made.')
            return

        created, skipped = 0, 0
        new_articles = []
        with transaction.atomic():
            resource_type, _ = ResourceType.objects.get_or_create(slug='heavy-cargo', defaults={'name':'大件知识','order':3})
            for entry in entries:
                if Article.objects.filter(slug=entry['slug']).exists():
                    skipped += 1
                    continue
                article = Article(
                    title=entry['title'], slug=entry['slug'], kind='resources', resource_type=resource_type,
                    category=entry['category'], summary=entry['summary'], body=entry['body'], body_format='markdown',
                    reviewed_on=entry['_reviewed'], original_source=entry['_original'].lstrip(), editorial_notes=entry['_notes'],
                    published=options['publish'], published_at=timezone.now() if options['publish'] else None,
                )
                article.full_clean()
                article.save()
                for slug in entry['countries']:
                    country, _ = Country.objects.get_or_create(slug=slug, defaults={'name':names[slug]})
                    article.countries.add(country)
                article.related_routes.add(*Route.objects.filter(slug__in=entry['routes']))
                for ref in entry['references']:
                    reference = ArticleReference(article=article, **ref)
                    reference.full_clean()
                    reference.save()
                new_articles.append((article, entry))
                created += 1
            for article, entry in new_articles:
                article.related_resources.add(*Article.objects.filter(slug__in=entry['related']))
        self.stdout.write(self.style.SUCCESS(f'Created {created}; published {created if options["publish"] else 0}; skipped existing {skipped}; source documents {len(documents)}. Existing content preserved.'))
