from django.contrib import admin
from django.utils import timezone
from .models import SiteSettings, Route, Article, Country, ResourceType, FreightRate
admin.site.site_header = '深圳昆腾 · 内容管理'
admin.site.site_title = '深圳昆腾管理后台'
@admin.register(SiteSettings)
class SiteAdmin(admin.ModelAdmin):
    def has_add_permission(self, request): return not SiteSettings.objects.exists()
    def has_delete_permission(self, request, obj=None): return False
@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'order']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
@admin.register(ResourceType)
class ResourceTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'order']
    prepopulated_fields = {'slug': ('name',)}
@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ['title','region','published','updated_at']
    list_filter = ['region','country_tags','published']
    search_fields = ['title','countries','country_tags__name']
    filter_horizontal = ['country_tags']
    prepopulated_fields = {'slug':('title',)}
@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ['title','kind','resource_type','category','published','published_at']
    list_filter = ['kind','resource_type','countries','published','category']
    search_fields = ['title','body','location']
    filter_horizontal = ['countries','related_routes','related_resources']
    prepopulated_fields = {'slug':('title',)}
    fieldsets = [
        ('基本内容', {'fields': ['title','slug','kind','category','resource_type','summary','body']}),
        ('国家与关联资料', {'fields':['countries','related_routes','related_resources']}),
        ('口岸、车型、桥梁资料（按需填写）', {'fields':['location','specifications','access_info','requirements','restrictions']}),
        ('来源与附件', {'fields':['author','source','attachment']}),
        ('发布设置', {'fields':['published','published_at']}),
    ]
    def save_model(self, request, obj, form, change):
        if obj.published and not obj.published_at: obj.published_at = timezone.now()
        super().save_model(request,obj,form,change)
@admin.register(FreightRate)
class FreightRateAdmin(admin.ModelAdmin):
    list_display = ['origin','destination','vehicle','price_min','price_max','currency','valid_until','validity_label','published']
    list_filter = ['published','currency','route']
    search_fields = ['origin','destination','vehicle','cargo','source']
    readonly_fields = ['updated_at','validity_label']
    prepopulated_fields = {'slug':('origin','destination','vehicle')}
    fieldsets = [
        ('运输需求', {'fields':['slug','route','origin','destination','vehicle','cargo']}),
        ('参考运价', {'fields':['price_min','price_max','currency','unit','terms','source','source_url']}),
        ('有效期与发布', {'fields':['valid_from','valid_until','validity_label','published','published_at','updated_at']}),
    ]
    def save_model(self, request, obj, form, change):
        if obj.published and not obj.published_at: obj.published_at = timezone.now()
        super().save_model(request,obj,form,change)
