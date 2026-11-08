"""Import country research with explicit evidence levels and private originals."""
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
    help = '导入64国研究资料及两篇导读；依据等级公开展示，原稿仅后台，保留管理员修改'

    def add_arguments(self, parser):
        parser.add_argument('--catalog', type=Path, default=settings.BASE_DIR / 'content/country-rules/catalog.json')
        parser.add_argument('--original-dir', type=Path, help='可选的私有原稿目录，按SHA256校验')
        parser.add_argument('--publish', action='store_true', help='仅发布本次新建文章，不发布已有草稿')
        parser.add_argument('--dry-run', action='store_true', help='核验数据与来源，不写入数据库')

    def handle(self, *args, **options):
        try:
            bundle = json.loads(options['catalog'].read_text(encoding='utf-8'))
            if bundle['version'] != 1:
                raise ValueError('Unsupported country research catalog version')
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
                if entry['routes']:
                    raise ValueError('Research coverage must not imply an offered transport route')
                if entry['evidence_level'] not in {'', 'A', 'B', 'C'}:
                    raise ValueError('Invalid evidence level')
                if entry['id'] not in {'EU', 'GUIDE'} and (not entry['evidence_level'] or len(entry['countries']) != 1):
                    raise ValueError('Country research requires one country and an evidence level')
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
            if len(documents) != bundle['source_document_count'] or len(entries) != bundle['country_article_count'] + 2:
                raise ValueError('Source or rule coverage mismatch')
            country_entries = [e for e in entries if e['id'] not in {'EU', 'GUIDE'}]
            if len(country_entries) != bundle['country_article_count'] or len({e['countries'][0] for e in country_entries}) != bundle['country_article_count']:
                raise ValueError('Country coverage mismatch')
            for entry in entries:
                for url in re.findall(r'\]\((/articles/[^)]+)\)', entry['body']):
                    if url.strip('/').split('/')[-1] not in slugs | {'heavy-cargo-handbook','bridge-handbook'}:
                        raise ValueError('Unmapped internal article link: ' + url)
                if re.search(r'\]\([^)]*\.md\)|admin\.ostoa|source_rule_|loading_rules|前端资源|SEO编辑|publication_review_required', entry['body']):
                    raise ValueError('Internal source data or unresolved Markdown link in public body')
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise CommandError(f'Invalid country research catalog: {exc}') from exc

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
                    category=entry['category'], evidence_level=entry['evidence_level'], summary=entry['summary'], body=entry['body'], body_format='markdown',
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
