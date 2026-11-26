import json
from types import SimpleNamespace
from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from web.models import Country
from web.templatetags.content import article_body
from .models import Category, Question


def schema_json(value): return json.dumps(value, ensure_ascii=False).replace('<', '\\u003c')
def absolute(path): return settings.SITE_URL + path


def breadcrumbs(items):
    return {'@type': 'BreadcrumbList', 'itemListElement': [
        {'@type': 'ListItem', 'position': i, 'name': name, 'item': absolute(url)} for i, (name, url) in enumerate(items, 1)]}


def listing(request, slug=None):
    category = get_object_or_404(Category, slug=slug, enabled=True) if slug else None
    public = Question.objects.public()
    items = public.select_related('category')
    if category: items = items.filter(category=category)
    q, country = request.GET.get('q', '').strip()[:160], request.GET.get('country', '')[:80]
    sort = request.GET.get('sort', 'recent')
    if sort not in ['recent', 'recommended']: sort = 'recent'
    if q:
        items = items.filter(Q(question__icontains=q) | Q(short_answer__icontains=q) | Q(body__icontains=q) | Q(alternative_questions__icontains=q))
    if country: items = items.filter(countries__slug=country)
    items = items.distinct().order_by(*(['-featured', 'order', '-updated_at', '-pk'] if sort == 'recommended' else ['-updated_at', '-pk']))
    page = Paginator(items, 12).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    canonical = absolute(request.path) + (f'?page={page.number}' if page.number > 1 else '')
    categories = Category.objects.filter(enabled=True).annotate(total=Count('questions', filter=Q(questions__published=True, questions__published_at__lte=timezone.now())))
    countries = Country.objects.filter(faqs__in=public).distinct()
    title = (category.seo_title or category.name + '常见问题') if category else '卡车 / 卡航 FAQ'
    description = (category.seo_description or category.description or category.name + '运输问答') if category else '按主题和国家查找国际卡车、卡航运输常见问题，了解线路、运价、车型、口岸及运输流程。'
    crumbs = [('首页', '/'), ('卡车 / 卡航 FAQ', reverse('faq-index'))]
    if category: crumbs.append((category.name, category.get_absolute_url()))
    schema = {'@context': 'https://schema.org', '@graph': [
        {'@type': 'CollectionPage', 'name': title, 'description': description, 'url': canonical, 'inLanguage': 'zh-CN',
         'mainEntity': {'@type': 'ItemList', 'itemListElement': [{'@type': 'ListItem', 'position': page.start_index()+i, 'name': item.question, 'url': absolute(item.get_absolute_url())} for i, item in enumerate(page)]}},
        breadcrumbs(crumbs)]}
    return render(request, 'faq/list.html', {
        'title': title, 'description': description, 'category': category, 'categories': categories,
        'countries': countries, 'q': q, 'country': country, 'sort': sort, 'page': page,
        'page_query': params.urlencode(), 'canonical': canonical, 'schema': schema_json(schema),
        'noindex': bool(q or country or sort != 'recent' or not page.paginator.count),
        'featured': public.filter(featured=True).order_by('order', '-updated_at', '-pk')[:4] if not category and not q and not country and page.number == 1 else [],
    })


def can_preview(user):
    return user.is_active and user.is_staff and (user.has_perm('faq.view_question') or user.has_perm('faq.change_question'))


def render_question(request, item, preview=False):
    answer_html = render_to_string('faq/answer.html', {'item': item, 'detail_html': article_body(SimpleNamespace(body_format='markdown', body=item.body))})
    crumbs = [('首页', '/'), ('卡车 / 卡航 FAQ', reverse('faq-index')), (item.category.name, item.category.get_absolute_url()), (item.question, item.get_absolute_url())]
    schema = {'@context': 'https://schema.org', '@graph': [
        {'@type': 'FAQPage', '@id': absolute(item.get_absolute_url())+'#faq', 'url': absolute(item.get_absolute_url()),
         'name': item.question, 'description': item.description, 'inLanguage': 'zh-CN',
         'dateModified': item.updated_at.isoformat(),
         'mainEntity': [{'@type': 'Question', 'name': item.question, 'acceptedAnswer': {'@type': 'Answer', 'text': answer_html}}]}, breadcrumbs(crumbs)]}
    faq_schema = schema['@graph'][0]
    if item.published_at: faq_schema['datePublished'] = item.published_at.isoformat()
    if item.author: faq_schema['author'] = {'@type': item.author_type, 'name': item.author}
    if item.reviewer: faq_schema['reviewedBy'] = {'@type': 'Person', 'name': item.reviewer}
    if item.reviewed_on: faq_schema['lastReviewed'] = item.reviewed_on.isoformat()
    references = list(item.references.all())
    if references: faq_schema['citation'] = [ref.url for ref in references]
    related = item.related_questions.public().exclude(pk=item.pk)
    if not related.exists(): related = Question.objects.public().filter(category=item.category).exclude(pk=item.pk)
    response = render(request, 'faq/detail.html', {
        'item': item, 'title': item.seo_title or item.question, 'description': item.description,
        'keywords': item.seo_keywords, 'canonical': absolute(item.get_absolute_url()),
        'answer_html': answer_html, 'schema': schema_json(schema), 'preview': preview, 'noindex': preview,
        'references': references, 'related_questions': related[:6],
        'related_routes': item.related_routes.filter(published=True),
        'related_resources': item.related_resources.filter(published=True, published_at__lte=timezone.now()),
    })
    if preview: response['X-Robots-Tag'] = 'noindex, nofollow'
    return response


def detail(request, slug):
    return render_question(request, get_object_or_404(Question.objects.public().select_related('category'), slug=slug))


@never_cache
def preview(request, pk):
    if not can_preview(request.user): raise Http404
    return render_question(request, get_object_or_404(Question.objects.select_related('category'), pk=pk), preview=True)


@never_cache
def image(request, slug):
    items = Question.objects.all() if request.GET.get('preview') == '1' and can_preview(request.user) else Question.objects.public()
    item = get_object_or_404(items, slug=slug)
    if not item.image: raise Http404
    response = FileResponse(item.image.open('rb'))
    response['X-Content-Type-Options'] = 'nosniff'
    response['X-Robots-Tag'] = 'noindex'
    return response
