import json
import re
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse, JsonResponse, FileResponse, Http404
from django.db.models import F, Q
from django.core.paginator import Paginator
from django.utils import timezone
from django.conf import settings
from .models import Route, Article, Country, ResourceType, FreightRate

def public_articles():
    return Article.objects.filter(published=True, published_at__lte=timezone.now())
def home(request):
    return render(request,'home.html',{'title':'国际公路整车运输','routes':Route.objects.filter(published=True)[:4],'articles':public_articles()[:3]})
def about(request): return render(request,'about.html',{'title':'关于我们'})
def contact(request): return render(request,'contact.html',{'title':'联系我们'})
def routes(request):
    region = request.GET.get('region','')
    items = Route.objects.filter(published=True)
    if region: items=items.filter(region=region)
    return render(request,'routes.html',{'title':'运输线路','routes':items,'regions':Route.REGIONS,'region':region})
def route(request, slug):
    item=get_object_or_404(Route,published=True,slug=slug)
    return render(request,'route.html',{'title':item.title,'description':item.summary,'item':item,'related_resources':item.resources.filter(published=True,published_at__lte=timezone.now()),'rates':public_rates().filter(route=item)[:3]})
def articles(request, kind):
    if kind not in ['news','resources']: raise Http404
    items = public_articles().filter(kind=kind).select_related('resource_type').prefetch_related('countries')
    if kind == 'news': items = items.exclude(category__in=['参考运价', '口岸动态'])
    q = request.GET.get('q','').strip()[:100]
    category = request.GET.get('category','')
    country = request.GET.get('country','')
    resource_type = request.GET.get('type','') if kind == 'resources' else ''
    category_items = items.filter(resource_type__slug=resource_type) if resource_type and resource_type != 'routes' else items
    categories = sorted(set(category_items.values_list('category',flat=True)))
    knowledge_guide = None
    if resource_type == 'knowledge' and not (q or category or country):
        knowledge_guide = public_articles().filter(slug='heavy-haul-handbook', kind='resources', resource_type__slug='knowledge').first()
    vehicle_guide = None
    if resource_type == 'vehicles' and not (q or category or country):
        vehicle_guide = public_articles().filter(slug='vehicle-handbook', kind='resources', resource_type__slug='vehicles').first()
    bridge_guide = None
    if resource_type == 'bridges' and not (q or category or country):
        bridge_guide = public_articles().filter(slug='bridge-handbook', kind='resources', resource_type__slug='bridges').first()
    heavy_cargo_guide = None
    country_rules_guide = None
    if resource_type == 'heavy-cargo' and not (q or category or country):
        heavy_cargo_guide = public_articles().filter(slug='heavy-cargo-handbook', kind='resources', resource_type__slug='heavy-cargo').first()
        country_rules_guide = public_articles().filter(slug='country-heavy-haul-handbook', kind='resources', resource_type__slug='heavy-cargo').first()
    route_items = Route.objects.filter(published=True).prefetch_related('country_tags')
    if q:
        items = items.filter(Q(title__icontains=q)|Q(body__icontains=q)|Q(summary__icontains=q)|Q(location__icontains=q)|Q(countries__name__icontains=q)).distinct()
        route_items = route_items.filter(Q(title__icontains=q)|Q(body__icontains=q)|Q(countries__icontains=q)|Q(country_tags__name__icontains=q)).distinct()
    if country:
        items = items.filter(countries__slug=country)
        route_items = route_items.filter(country_tags__slug=country)
    if category: items = items.filter(category=category)
    if resource_type and resource_type != 'routes': items = items.filter(resource_type__slug=resource_type)
    # Routes are shared records, not copied into resource articles.
    if resource_type == 'routes': items = route_items
    params = request.GET.copy()
    params.pop('page', None)
    params.pop('type', None)
    filter_params = params.copy()
    filter_params.pop('category', None)
    filter_query = filter_params.urlencode()
    params['type'] = resource_type
    page_query = params.urlencode()
    page = Paginator(items,9).get_page(request.GET.get('page'))
    return render(request,'articles.html',{
        'title':'行业资讯' if kind=='news' else '资源库', 'page':page,'q':q,'kind':kind,
        'category':category,'categories':categories,'countries':Country.objects.all(),'country':country,
        'resource_types':ResourceType.objects.all(),'resource_type':resource_type,'knowledge_guide':knowledge_guide,
        'vehicle_guide':vehicle_guide,
        'bridge_guide':bridge_guide,
        'heavy_cargo_guide':heavy_cargo_guide,
        'country_rules_guide':country_rules_guide,
        'route_preview':route_items[:3] if kind == 'resources' and not resource_type and not category else [],
        'filter_query':filter_query,'page_query':page_query,
    })
def article(request,slug):
    item=get_object_or_404(public_articles(),slug=slug)
    if hasattr(item, 'cgr_report'):
        from cgr.views import detail
        return detail(request, item.cgr_report)
    keywords=list(dict.fromkeys(word.strip() for word in re.split('[,，]',item.seo_keywords) if word.strip()))
    schema={'@context':'https://schema.org','@type':'Article','headline':item.title,'description':item.summary,'datePublished':item.published_at.isoformat(),'dateModified':item.updated_at.isoformat(),'author':{'@type':'Organization','name':item.author},'mainEntityOfPage':settings.SITE_URL+item.get_absolute_url(),'inLanguage':'zh-CN','articleSection':item.category}
    if keywords: schema['keywords']=keywords
    context={'title':item.seo_title or item.title,'description':item.summary,'keywords':', '.join(keywords),'is_article':True,'item':item,'related_resources':item.related_resources.filter(published=True,published_at__lte=timezone.now()),'related_routes':item.related_routes.filter(published=True)}
    template='article.html'
    if hasattr(item, 'horgos_report'):
        from horgos.presentation import report_context
        context.update(report_context(item.horgos_report))
        template='horgos/report.html'
        schema['citation']='中国电子口岸'
    context['schema']=json.dumps(schema,ensure_ascii=False).replace(chr(60),chr(92)+'u003c')
    return render(request,template,context)
def download(request,slug):
    item=get_object_or_404(public_articles(),slug=slug)
    if not item.attachment: raise Http404
    return FileResponse(item.attachment.open('rb'),as_attachment=True,filename=item.attachment.name.rsplit('/',1)[-1])
def robots(request):
    return HttpResponse('User-agent: *\nDisallow: /admin/\nDisallow: /media/\nSitemap: '+settings.SITE_URL+'/sitemap.xml\n',content_type='text/plain')
def health(request):
    from django.db import connection
    with connection.cursor() as c: c.execute('SELECT 1')
    return JsonResponse({'status':'ok'})

def contact_qr(request):
    from .models import SiteSettings
    site = SiteSettings.objects.first()
    if not site or not site.qr: raise Http404
    return FileResponse(site.qr.open('rb'))

def public_rates():
    return FreightRate.objects.filter(published=True, published_at__lte=timezone.now(), route__published=True).select_related('route')

def freight_rates(request):
    items = public_rates()
    reports = public_articles().filter(kind='news', category='参考运价').prefetch_related('countries').order_by(F('quote_date').desc(nulls_last=True), '-published_at', '-pk')
    q = request.GET.get('q','').strip()[:100]
    country = request.GET.get('country','')
    status = request.GET.get('status','')
    today = timezone.localdate()
    if q:
        items = items.filter(Q(origin__icontains=q)|Q(destination__icontains=q)|Q(vehicle__icontains=q)|Q(cargo__icontains=q)|Q(route__title__icontains=q))
        reports = reports.filter(Q(title__icontains=q)|Q(summary__icontains=q)|Q(body__icontains=q))
    if country:
        items = items.filter(route__country_tags__slug=country)
        reports = reports.filter(countries__slug=country)
    if status == 'valid': items = items.filter(valid_from__lte=today, valid_until__gte=today)
    elif status == 'expired': items = items.filter(valid_until__lt=today)
    elif status == 'upcoming': items = items.filter(valid_from__gt=today)
    if status in ['valid','expired','upcoming']: reports = reports.none()
    elif status == 'reports': items = items.none()
    params = request.GET.copy()
    params.pop('page',None)
    report_params = request.GET.copy()
    report_params.pop('report_page',None)
    return render(request,'rates.html',{'title':'参考运价','page':Paginator(items,9).get_page(request.GET.get('page')),'report_page':Paginator(reports,9).get_page(request.GET.get('report_page')),'q':q,'country':country,'countries':Country.objects.all(),'status':status,'page_query':params.urlencode(),'report_page_query':report_params.urlencode()})

def freight_rate(request,slug):
    item = get_object_or_404(public_rates(),slug=slug)
    return render(request,'rate.html',{'title':str(item),'item':item,'description':'管理员维护的整车运输参考运价；请核对有效期与适用条件。'})

def resource_image(request,slug):
    item = get_object_or_404(public_articles(),slug=slug)
    if not item.image: raise Http404
    variant=request.GET.get('size','')
    from .image_variants import SIZES,display_image
    from PIL import Image,UnidentifiedImageError
    if variant and variant not in SIZES: raise Http404
    try:
        response = HttpResponse(display_image(item.image,variant),content_type='image/webp') if variant else FileResponse(item.image.open('rb'))
    except (OSError,UnidentifiedImageError,Image.DecompressionBombError):
        raise Http404 from None
    response['Cache-Control'] = 'no-store'
    return response
