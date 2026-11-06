from django.contrib import admin
from django.urls import path
from django.contrib.sitemaps.views import sitemap
from web import views
from web.sitemaps import Pages, Routes, Articles, FreightRates
urlpatterns = [path('prices/',views.freight_rates,name='prices'),path('prices/<slug:slug>/',views.freight_rate,name='freight-rate'),path('contact/qr/',views.contact_qr,name='contact-qr'),path('',views.home,name='home'),path('about/',views.about,name='about'),path('contact/',views.contact,name='contact'),path('routes/',views.routes,name='routes'),path('routes/<slug:slug>/',views.route,name='route'),path('news/',views.articles,{'kind':'news'},name='news'),path('resources/',views.articles,{'kind':'resources'},name='resources'),path('articles/<slug:slug>/',views.article,name='article'),path('download/<slug:slug>/',views.download,name='download'),path('admin/',admin.site.urls),path('robots.txt',views.robots),path('healthz/',views.health),path('sitemap.xml',sitemap,{'sitemaps':{'pages':Pages,'routes':Routes,'articles':Articles,'prices':FreightRates}})]
