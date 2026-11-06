import copy
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from web.models import Article, ArticleReference, Country, ResourceType
from web.port_review import article_digest, catalog_digest


class PortReviewTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.catalog=json.loads((settings.BASE_DIR/'content/ports/catalog.json').read_text(encoding='utf-8'))
        self.manifest=json.loads((settings.BASE_DIR/'content/ports/review-20261107.json').read_text(encoding='utf-8'))
        self.targets={entry['slug'] for entry in self.manifest['entries']}
        self.entries={entry['slug']:entry for entry in self.catalog['entries']}
        self.resource_type,_=ResourceType.objects.get_or_create(slug='ports',defaults={'name':'口岸介绍'})
        self.country=Country.objects.create(slug='example-review-country',name='测试国家')

    def make_draft(self,slug):
        article=Article.objects.create(
            slug=slug,title='Original draft '+slug,kind='resources',resource_type=self.resource_type,
            body='Unreviewed baseline',summary='Original summary',body_format='markdown',
            original_source='PRIVATE-ORIGINAL-'+slug,editorial_notes='Imported draft',
            image='articles/original-photo.jpg',image_caption='Original supplied caption',
        )
        article.countries.add(self.country)
        ArticleReference.objects.create(article=article,title='Old reference',url='https://example.com/original',note='Old note')
        return article

    def revision_for(self,articles):
        revision=copy.deepcopy(self.manifest)
        by_slug={article.slug:article for article in articles}
        revision['entries']=[target for target in revision['entries'] if target['slug'] in by_slug]
        for target in revision['entries']:
            target['before_sha256']=article_digest(by_slug[target['slug']])
        path=self.root/'revision.json'
        path.write_text(json.dumps(revision),encoding='utf-8')
        return path

    def publish(self,**kwargs):
        call_command('publish_reviewed_ports',stdout=StringIO(),**kwargs)

    def test_edition_contains_exactly_50_reviewed_targets_and_corrected_claims(self):
        self.assertEqual(len(self.targets),50)
        self.assertEqual(len(self.manifest['entries']),50)
        self.assertEqual(len(self.entries),66)
        for target in self.manifest['entries']:
            entry=self.entries[target['slug']]
            self.assertTrue(entry['reviewed'])
            self.assertTrue(entry['references'])
            self.assertEqual(entry['reviewed_on'],'2026-11-07')
            self.assertEqual(catalog_digest(entry),target['after_sha256'])
            self.assertNotEqual(target['before_sha256'],target['after_sha256'])
            self.assertNotIn('> 编辑草稿',entry['body'])
        self.assertIn('里板',self.entries['port-0409']['body'])
        self.assertIn('2025年3月31日',self.entries['port-0510']['body'])
        self.assertIn('不能直接作为已恢复运营',self.entries['port-0307']['body'])
        self.assertIn('不能直接把铁路口岸作为货车过境点',self.entries['port-0402']['body'])
        self.assertEqual(sum(bool(entry.get('photo')) for entry in self.entries.values()),66)

    def test_upgrade_all_50_preserves_original_media_tags_and_other_articles(self):
        drafts=[self.make_draft(slug) for slug in sorted(self.targets)]
        revision=self.revision_for(drafts)
        unrelated=self.make_draft('port-unrelated')
        unrelated_before=article_digest(unrelated)
        self.publish(revision=revision)
        self.assertEqual(Article.objects.filter(published=True).count(),50)
        for article in drafts:
            article.refresh_from_db()
            self.assertEqual(article_digest(article),catalog_digest(self.entries[article.slug]))
            self.assertTrue(article.published)
            self.assertLessEqual(article.published_at,timezone.now())
            self.assertEqual(article.original_source,'PRIVATE-ORIGINAL-'+article.slug)
            self.assertEqual(article.image.name,'articles/original-photo.jpg')
            self.assertEqual(article.image_caption,'Original supplied caption')
            self.assertEqual(list(article.countries.values_list('pk',flat=True)),[self.country.pk])
        unrelated.refresh_from_db()
        self.assertEqual(article_digest(unrelated),unrelated_before)
        self.assertFalse(unrelated.published)
        # A rerun must preserve later administrator edits and unpublication.
        article=drafts[0]
        article.body='Administrator revision after publication'
        article.published=False
        article.save()
        self.publish(revision=revision)
        article.refresh_from_db()
        self.assertEqual(article.body,'Administrator revision after publication')
        self.assertFalse(article.published)

    def test_changed_final_draft_aborts_entire_batch_before_writing(self):
        first=self.make_draft('port-0103')
        last=self.make_draft('port-0510')
        revision=self.revision_for([first,last])
        first_before=article_digest(first)
        last.body='Administrator correction before review'
        last.save()
        with self.assertRaisesMessage(CommandError,'Port changed since review baseline'):
            self.publish(revision=revision)
        first.refresh_from_db()
        last.refresh_from_db()
        self.assertEqual(article_digest(first),first_before)
        self.assertFalse(first.published)
        self.assertEqual(last.body,'Administrator correction before review')

    def test_dry_run_validates_without_changing_draft_or_references(self):
        article=self.make_draft('port-0103')
        before=article_digest(article)
        revision=self.revision_for([article])
        self.publish(revision=revision,dry_run=True)
        article.refresh_from_db()
        self.assertEqual(article_digest(article),before)
        self.assertFalse(article.published)
        self.assertIsNone(article.published_at)

    def test_reference_edit_and_prior_publication_are_protected(self):
        article=self.make_draft('port-0103')
        revision=self.revision_for([article])
        source=article.references.get()
        source.note='Administrator fact check'
        source.save()
        with self.assertRaises(CommandError):
            self.publish(revision=revision)
        source.note='Old note'
        source.save()
        article.published_at=timezone.now()
        article.save()
        with self.assertRaises(CommandError):
            self.publish(revision=revision)

    def test_tampered_release_and_missing_target_do_not_create_content(self):
        with self.assertRaisesMessage(CommandError,'Missing port'):
            self.publish()
        self.assertFalse(Article.objects.exists())
        article=self.make_draft('port-0103')
        revision=self.revision_for([article])
        self.entries[article.slug]['body']='Unexpected changed catalog'
        catalog=self.root/'tampered.json'
        catalog.write_text(json.dumps(self.catalog),encoding='utf-8')
        with self.assertRaisesMessage(CommandError,'does not match the release manifest'):
            self.publish(catalog=catalog,revision=revision)
        article.refresh_from_db()
        self.assertFalse(article.published)
