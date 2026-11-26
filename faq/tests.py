from datetime import timedelta
from io import BytesIO
import json
import re
from tempfile import TemporaryDirectory
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from .models import Category, Question, Reference
from web.models import Country


@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class FAQTests(TestCase):
    def setUp(self):
        self.category = Category.objects.get(slug='basics')
        self.user = get_user_model().objects.create_superuser('faq-admin', password='test-only')

    def question(self, **kwargs):
        defaults = dict(category=self.category, question='卡航运输询价需要哪些资料？', short_answer='提供货物尺寸、毛重、起讫地与计划出运日期。')
        defaults.update(kwargs)
        return Question.objects.create(**defaults)

    def schema(self, response):
        return json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', response.content.decode(), re.S)[1])

    def test_initial_categories_without_sample_content(self):
        self.assertEqual(Category.objects.count(), 8)
        self.assertEqual(Question.objects.count(), 0)
        response = self.client.get('/faq/')
        self.assertContains(response, '内容正在整理中')
        self.assertContains(response, 'noindex,follow')
        self.assertNotContains(self.client.get('/sitemap.xml'), '/faq/')
        for category in Category.objects.all(): self.assertEqual(self.client.get(category.get_absolute_url()).status_code, 200)

    def test_public_question_schema_matches_visible_answer_and_fallback_seo(self):
        item = self.question(published=True, body='## 准备资料\n\n- 每件尺寸\n- 毛重', scope='适用于整车运输询价。', editorial_notes='PRIVATE-EDITORIAL', alternative_questions='PRIVATE-SEARCH-ALIAS')
        Reference.objects.create(question=item, title='业务资料', url='https://example.com/reference', note='核对说明')
        response = self.client.get(item.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        schema = self.schema(response)['@graph'][0]
        self.assertEqual(schema['@type'], 'FAQPage')
        self.assertEqual(schema['mainEntity'][0]['name'], item.question)
        self.assertIn(schema['mainEntity'][0]['acceptedAnswer']['text'], response.content.decode())
        self.assertEqual(schema['datePublished'], item.published_at.isoformat())
        self.assertEqual(schema['citation'], ['https://example.com/reference'])
        self.assertContains(response, item.description)
        self.assertNotContains(response, 'PRIVATE-EDITORIAL')
        self.assertNotContains(response, 'PRIVATE-SEARCH-ALIAS')
        sitemap = self.client.get('/sitemap.xml')
        for path in ['/faq/', self.category.get_absolute_url(), item.get_absolute_url()]: self.assertContains(sitemap, path)
        self.assertNotContains(sitemap, '/faq/category/pricing-and-fees/')

    def test_drafts_future_disabled_categories_not_discoverable(self):
        for state in ['draft', 'future', 'disabled']:
            category = Category.objects.create(name=state, enabled=state!='disabled')
            item = self.question(question='PRIVATE-'+state, category=category, published=state!='draft', published_at=timezone.now()+timedelta(days=1) if state=='future' else timezone.now())
            for suffix in ['', '?preview=1']:
                self.assertEqual(self.client.get(item.get_absolute_url()+suffix).status_code, 404)
            for path in ['/faq/', '/faq/?q=PRIVATE', '/sitemap.xml']:
                response = self.client.get(path)
                self.assertNotContains(response, item.question)
                self.assertNotContains(response, item.get_absolute_url())
        self.assertEqual(self.client.get(category.get_absolute_url()).status_code, 404)

    def test_preview_requires_faq_permission_and_is_not_indexable(self):
        item = self.question()
        url = reverse('faq-preview', args=[item.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        user = get_user_model().objects.create_user('staff', is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get(url).status_code, 404)
        user.user_permissions.add(Permission.objects.get(codename='view_question', content_type__app_label='faq'))
        response = self.client.get(url)
        self.assertContains(response, item.short_answer)
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertNotContains(response, 'application/ld+json')

    def test_search_country_filter_aliases_sorting_and_pagination(self):
        country = Country.objects.create(name='验收国家', slug='qa-country')
        selected = self.question(question='专用问答', published=True, alternative_questions='特殊问法', featured=True)
        selected.countries.add(country)
        for index in range(14): self.question(question=f'其他问题 {index}', published=True)
        response = self.client.get('/faq/?q=特殊问法&country=qa-country')
        self.assertContains(response, '专用问答')
        self.assertNotContains(response, '其他问题 0')
        self.assertContains(response, 'noindex,follow')
        self.assertEqual(self.client.get('/faq/?sort=recommended').context['page'][0].pk, selected.pk)
        second = self.client.get('/faq/?page=2')
        self.assertEqual(len(second.context['page']), 3)
        self.assertTrue(second.context['canonical'].endswith('/faq/?page=2'))
        self.assertEqual(self.schema(second)['@graph'][0]['mainEntity']['itemListElement'][0]['position'], 13)

    def test_sanitizes_answer_and_json_script(self):
        item = self.question(published=True, question='问题</script><script>alert(1)</script>', short_answer='<img src=x onerror=alert(2)>', body='[链接](javascript:alert(1))\n\n<script>alert(3)</script>')
        response = self.client.get(item.get_absolute_url())
        self.assertNotContains(response, '<script>alert(')
        self.assertNotContains(response, 'href="javascript:')
        self.assertNotContains(response, '<img src=x')
        self.assertEqual(self.schema(response)['@graph'][0]['mainEntity'][0]['name'], item.question)

    def test_urls_stable_and_empty_answers_invalid(self):
        item = self.question(published=True)
        url = item.get_absolute_url()
        item.question = '修改后的问题'
        item.save()
        self.assertEqual(item.get_absolute_url(), url)
        item.slug = 'changed-url'
        with self.assertRaises(ValidationError): item.full_clean()
        draft = self.question(short_answer='  ')
        with self.assertRaises(ValidationError): draft.full_clean()
        with self.assertRaises(ProtectedError): self.category.delete()

    def test_admin_publish_withdraw_and_related_privacy(self):
        item = self.question()
        secret = self.question(question='PRIVATE-RELATED')
        item.related_questions.add(secret)
        self.client.force_login(self.user)
        url = reverse('admin:faq_question_changelist')
        response = self.client.post(url, {'action': 'publish', '_selected_action': item.pk})
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertTrue(item.published)
        self.assertIsNotNone(item.published_at)
        self.assertNotContains(self.client.get(item.get_absolute_url()), 'PRIVATE-RELATED')
        self.client.post(url, {'action': 'withdraw', '_selected_action': item.pk})
        self.assertEqual(self.client.get(item.get_absolute_url()).status_code, 404)
        self.assertNotContains(self.client.get('/sitemap.xml'), item.get_absolute_url())

    def test_admin_add_edit_preview_sources_and_similar_warning(self):
        self.question(question='卡航运输询价需要哪些资料？')
        self.client.force_login(self.user)
        data = {'question': '卡航运输询价需要什么资料？', 'category': self.category.pk, 'short_answer': '尺寸、毛重、起讫地。', 'author': '深圳昆腾编辑部', 'author_type': 'Organization', 'order': 0, 'references-TOTAL_FORMS': 1, 'references-INITIAL_FORMS': 0, 'references-MIN_NUM_FORMS': 0, 'references-MAX_NUM_FORMS': 1000, 'references-0-title': '业务资料', 'references-0-url': 'https://example.com/reference', '_save': '保存'}
        response = self.client.post(reverse('admin:faq_question_add'), data, follow=True)
        self.assertContains(response, '发现相似问题')
        item = Question.objects.get(question=data['question'])
        self.assertEqual(item.references.count(), 1)
        self.assertEqual(self.client.get(reverse('admin:faq_question_change', args=[item.pk])).status_code, 200)
        self.assertContains(self.client.get(reverse('faq-preview', args=[item.pk])), '尺寸、毛重、起讫地。')

    def test_draft_image_access_matches_question_access(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            raw = BytesIO()
            Image.new('RGB', (2, 2), 'red').save(raw, format='PNG')
            item = self.question(image=SimpleUploadedFile('example.png', raw.getvalue(), content_type='image/png'))
            url = reverse('faq-image', args=[item.slug])
            self.assertEqual(self.client.get(url+'?preview=1').status_code, 404)
            self.client.force_login(self.user)
            response = self.client.get(url+'?preview=1')
            self.assertEqual(response.status_code, 200)
            response.close()
            self.client.logout()
            item.published=True; item.save()
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            response.close()

    def test_country_shortcuts_count_only_public_category_content_and_reset_page(self):
        country = Country.objects.create(name='国家快捷入口验收', slug='qa-uzbekistan')
        item = self.question(published=True)
        item.countries.add(country)
        self.question(question='未关联国家的问题', published=True)
        hidden = self.question(question='PRIVATE COUNTRY COUNT')
        hidden.countries.add(country)
        other = self.question(category=Category.objects.get(slug='pricing-and-fees'), published=True)
        other.countries.add(country)
        response = self.client.get(self.category.get_absolute_url()+'?q=询价&sort=recommended&page=2')
        countries = response.context['countries']
        self.assertEqual([(c.slug, c.total) for c in countries], [('qa-uzbekistan', 1)])
        self.assertEqual(response.context['country_total'], 2)
        self.assertIn('q=', countries[0].filter_url)
        self.assertIn('sort=recommended', countries[0].filter_url)
        self.assertNotIn('page=', countries[0].filter_url)
        self.assertContains(response, 'aria-label="按国家浏览问答"')
        self.assertContains(response, 'faq-question-countries')
