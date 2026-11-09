from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from .models import Route
from .views import public_articles, public_rates
class Pages(Sitemap):
    protocol='https'
    def items(self): return ['home','about','contact','routes','news','resources','prices','border-updates']
    def location(self,item): return reverse(item)
class Routes(Sitemap):
    protocol='https'
    def items(self): return Route.objects.filter(published=True)
    def lastmod(self,obj): return obj.updated_at
class Articles(Sitemap):
    protocol='https'
    def items(self): return public_articles()
    def lastmod(self,obj): return obj.updated_at

class FreightRates(Sitemap):
    protocol='https'
    def items(self): return public_rates()
    def lastmod(self,obj): return obj.updated_at
