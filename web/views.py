import json
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse, JsonResponse, FileResponse, Http404
from django.db.models import Q
from django.core.paginator import Paginator
from django.utils import timezone
from django.conf import settings
from .models import Route, Article

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
    return render(request,'route.html',{'title':item.title,'description':item.summary,'item':item})
def articles(request, kind):
    if kind not in ['news','resources']: raise Http404
    items=public_articles().filter(kind=kind)
    categories=list(items.values_list('category',flat=True).distinct())
    q=request.GET.get('q','').strip()[:100]
    category=request.GET.get('category','')
    if q: items=items.filter(Q(title__icontains=q)|Q(body__icontains=q)|Q(summary__icontains=q))
    if category: items=items.filter(category=category)
    page=Paginator(items,9).get_page(request.GET.get('page'))
    return render(request,'articles.html',{'title':'行业资讯' if kind=='news' else '资源库','page':page,'q':q,'kind':kind,'category':category,'categories':sorted(set(categories))})
def article(request,slug):
    item=get_object_or_404(public_articles(),slug=slug)
    schema={'@context':'https://schema.org','@type':'Article','headline':item.title,'description':item.summary,'datePublished':item.published_at.isoformat(),'dateModified':item.updated_at.isoformat(),'author':{'@type':'Organization','name':item.author},'mainEntityOfPage':settings.SITE_URL+item.get_absolute_url()}
    return render(request,'article.html',{'title':item.title,'description':item.summary,'item':item,'schema':json.dumps(schema,ensure_ascii=False).replace(chr(60),chr(92)+'u003c')})
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
