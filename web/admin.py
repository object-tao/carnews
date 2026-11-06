from django.contrib import admin
from django.utils import timezone
from .models import SiteSettings, Route, Article
admin.site.site_header = '深圳昆腾 · 内容管理'
admin.site.site_title = '深圳昆腾管理后台'
@admin.register(SiteSettings)
class SiteAdmin(admin.ModelAdmin):
    def has_add_permission(self, request): return not SiteSettings.objects.exists()
    def has_delete_permission(self, request, obj=None): return False
@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ['title','region','published','updated_at']
    list_filter = ['region','published']
    search_fields = ['title','countries']
    prepopulated_fields = {'slug':('title',)}
@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ['title','kind','category','published','published_at']
    list_filter = ['kind','published','category']
    search_fields = ['title','body']
    prepopulated_fields = {'slug':('title',)}
    def save_model(self, request, obj, form, change):
        if obj.published and not obj.published_at: obj.published_at = timezone.now()
        super().save_model(request,obj,form,change)
