from django.contrib.sitemaps import Sitemap
from django.db.models import Max
from django.urls import reverse
from .models import Category, Question


class FAQPages(Sitemap):
    protocol = 'https'
    def items(self): return ['faq-index'] if Question.objects.public().exists() else []
    def location(self, item): return reverse(item)
    def lastmod(self, item): return Question.objects.public().aggregate(value=Max('updated_at'))['value']


class FAQCategories(Sitemap):
    protocol = 'https'
    def items(self):
        return Category.objects.filter(questions__in=Question.objects.public()).annotate(last_update=Max('questions__updated_at')).order_by('order', 'pk')
    def lastmod(self, item): return item.last_update


class FAQQuestions(Sitemap):
    protocol = 'https'
    def items(self): return Question.objects.public()
    def lastmod(self, item): return item.updated_at
