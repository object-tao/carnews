from datetime import date, timedelta
from itertools import groupby
import json
from urllib.parse import urlencode
from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from .catalog import COUNTRIES, SOURCE_URL
from .models import Checkpoint, CollectionRun, DailyReport


def public_reports():
    return DailyReport.objects.filter(article__published=True, article__published_at__lte=timezone.now(), run__status='success').select_related('article', 'run')


def may_preview(request):
    return request.GET.get('preview') == '1' and request.user.has_perm('cgr.view_dailyreport')


def filtered_observations(request, report):
    country = request.GET.get('country', '')
    node = request.GET.get('port', '')
    q = request.GET.get('q', '').strip()[:100]
    day = request.GET.get('day', '')
    if country and country not in dict(COUNTRIES):
        raise ValueError('请选择有效的国家或地区。')
    if node and (not node.isascii() or not node.isdigit() or len(node) > 10):
        raise ValueError('请选择有效的口岸。')
    selected_day = date.fromisoformat(day) if day else None
    # Public access is based on the report's immutable selected run, never an arbitrary run id.
    items = report.run.observations.select_related('checkpoint', 'checkpoint__article').order_by('checkpoint__country', 'checkpoint_id', 'day')
    if country:
        items = items.filter(checkpoint__country=country)
    if node:
        items = items.filter(checkpoint_id=int(node))
    if q:
        q = q.replace('波基图', '巴克图').replace('杜拉特', '都拉塔')
        items = items.filter(Q(checkpoint__name__icontains=q) | Q(checkpoint__source_name__icontains=q))
    if selected_day:
        items = items.filter(day=selected_day)
    return items


def report_context(request, report):
    observations = list(filtered_observations(request, report))
    dates = sorted({o.day for o in observations})
    grouped = []
    for code, label in COUNTRIES:
        nodes = []
        country_rows = [o for o in observations if o.checkpoint.country == code]
        for _, group in groupby(country_rows, key=lambda o: o.checkpoint_id):
            cells = list(group)
            checkpoint = cells[0].checkpoint
            tiers = sorted({tier for cell in cells for tier in cell.quotas}, key=int)
            earliest = []
            for tier in tiers:
                first = next((cell for cell in cells if cell.quotas.get(tier, 0) > 0), None)
                earliest.append({'tier': tier, 'day': first.day if first else None})
            for cell in cells:
                cell.tooltip = f'{cell.day} · {cell.get_state_display()} ' + ' / '.join(f'{tier} МРП: {value}' for tier, value in cell.quotas.items())
            article = checkpoint.article
            info_url = article.get_absolute_url() if article and article.published and article.published_at and article.published_at <= timezone.now() else ''
            nodes.append({'checkpoint': checkpoint, 'cells': cells, 'first': cells[0], 'earliest': earliest, 'info_url': info_url})
        if nodes:
            grouped.append({'code': code, 'name': label, 'nodes': nodes})
    ports = Checkpoint.objects.filter(observation__run=report.run).distinct()
    if request.GET.get('country'):
        ports = ports.filter(country=request.GET['country'])
    parameters = request.GET.copy()
    parameters.pop('page', None)
    parameters.pop('history_page', None)
    parameters.pop('date', None)
    query = parameters.urlencode()
    latest_run = CollectionRun.objects.order_by('-started_at', '-pk').first()
    stale = report.run.started_at < timezone.now() - timedelta(hours=26)
    recent_failure = bool(latest_run and latest_run.status == 'failed' and latest_run.started_at > report.run.started_at)
    return {
        'report': report, 'item': report.article, 'groups': grouped, 'dates': dates,
        'observations': observations, 'page': Paginator(observations, 100).get_page(request.GET.get('page')),
        'ports': ports, 'country_options': COUNTRIES, 'country': request.GET.get('country', ''),
        'selected_port': request.GET.get('port', ''), 'q': request.GET.get('q', '').strip()[:100],
        'selected_day': request.GET.get('day', ''), 'filter_query': query,
        'page_query': urlencode({**parameters.dict(), **({'date': request.GET['date']} if request.GET.get('date') else {})}),
        'node_count': sum(len(g['nodes']) for g in grouped), 'row_count': len(observations),
        'stale': stale, 'recent_failure': recent_failure, 'source_url': SOURCE_URL,
        'is_preview': may_preview(request),
        'related_resources': report.article.related_resources.filter(published=True, published_at__lte=timezone.now()),
    }


def dashboard(request):
    reports = public_reports()
    selected = request.GET.get('date')
    if selected:
        try:
            report = get_object_or_404(reports, date=date.fromisoformat(selected))
        except ValueError:
            return HttpResponseBadRequest('报告日期格式应为 YYYY-MM-DD。')
    else:
        report = reports.first()
    context = {'title': '口岸动态：哈萨克斯坦与中国、俄罗斯及周边口岸预约',
               'description': '按国家、口岸与日期查看哈萨克斯坦口岸预约日报、可预约名额和日历，下载Excel与CSV清单。每日定时采集，保留历史快照。',
               'history': Paginator(reports, 10).get_page(request.GET.get('history_page')), 'country_options': COUNTRIES}
    if report:
        try:
            context.update(report_context(request, report))
        except ValueError:
            return HttpResponseBadRequest('筛选参数无效，请核对国家、口岸与预约日期。')
    return render(request, 'cgr/dashboard.html', context)


def detail(request, report):
    try:
        context = report_context(request, report)
    except ValueError:
        return HttpResponseBadRequest('筛选参数无效，请核对国家、口岸与预约日期。')
    item = report.article
    schema = {'@context': 'https://schema.org', '@type': 'Article', 'headline': item.title,
              'description': item.summary, 'datePublished': item.published_at.isoformat() if item.published_at else None,
              'dateModified': item.updated_at.isoformat(), 'inLanguage': 'zh-CN', 'articleSection': '口岸动态',
              'mainEntityOfPage': settings.SITE_URL + item.get_absolute_url(),
              'author': {'@type': 'Organization', 'name': item.author}, 'citation': SOURCE_URL,
              'keywords': item.seo_keywords.split(',')}
    context.update(title=item.seo_title or item.title, description=item.summary, keywords=item.seo_keywords,
                   is_article=True, schema=json.dumps(schema, ensure_ascii=False).replace('<', '\\u003c'))
    response = render(request, 'cgr/report.html', context)
    if may_preview(request):
        response['X-Robots-Tag'] = 'noindex, nofollow'
        response['Cache-Control'] = 'private, no-store'
    return response


def preview(request, pk):
    if not may_preview(request):
        raise Http404
    return detail(request, get_object_or_404(DailyReport.objects.select_related('article', 'run'), pk=pk, run__status='success'))


def export(request, pk, format):
    from .exports import make_export
    reports = DailyReport.objects.select_related('article', 'run').filter(run__status='success') if may_preview(request) else public_reports()
    report = get_object_or_404(reports, pk=pk)
    if format not in ('csv', 'xlsx', 'html'):
        raise Http404
    try:
        observations = list(filtered_observations(request, report))
    except ValueError:
        return HttpResponseBadRequest('筛选参数无效。')
    data, content_type = make_export(report, observations, format)
    response = HttpResponse(data, content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="CGR-{report.date}-run-{report.run_id}.{format}"'
    response['X-Robots-Tag'] = 'noindex'
    response['Cache-Control'] = 'private, no-store' if may_preview(request) else 'no-store'
    return response
