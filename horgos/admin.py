from django.contrib import admin, messages
from django.db import transaction
from django.utils import timezone
from django.urls import reverse
from django.utils.html import format_html
from .models import Settings, Run, Summary, Vehicle, VehicleVersion, Report
from cgr.admin import ReadOnlyAdmin


@admin.register(Settings)
class SettingsAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'enabled', 'auto_publish', 'requested_at']
    fields = ['enabled', 'daily_time', 'auto_publish', 'requested_at', 'handled_request_at', 'lease_until']
    readonly_fields = ['requested_at', 'handled_request_at', 'lease_until']
    actions = ['request_collection']

    def has_add_permission(self, request): return not Settings.objects.exists()
    def has_delete_permission(self, request, obj=None): return False

    @admin.action(description='立即补采当前数据', permissions=['change'])
    def request_collection(self, request, queryset):
        queryset.update(requested_at=timezone.now())
        self.message_user(request, '补采请求已排队，通常一分钟内启动；仅采集当前业务日期。')


@admin.register(Vehicle)
class VehicleAdmin(ReadOnlyAdmin):
    list_display = ['kind', 'number', 'company', 'status', 'occurred_at', 'first_seen', 'last_seen']
    list_filter = ['kind', 'status', 'occurred_at']
    date_hierarchy = 'occurred_at'
    search_fields = ['number', 'company']
    readonly_fields = [f.name for f in Vehicle._meta.fields]


@admin.register(VehicleVersion)
class VersionAdmin(ReadOnlyAdmin):
    list_display = ['vehicle', 'company', 'status', 'first_seen', 'last_seen']
    list_filter = ['vehicle__kind', 'status', 'vehicle__occurred_at', 'runs__date']
    search_fields = ['vehicle__number', 'company']
    list_select_related = ['vehicle']
    readonly_fields = [f.name for f in VehicleVersion._meta.fields]

    def lookup_allowed(self, lookup, value, request=None):
        if lookup == 'runs__id__exact': return str(value).isdigit()
        return super().lookup_allowed(lookup, value, request)


@admin.register(Summary)
class SummaryAdmin(ReadOnlyAdmin):
    list_display = ['date', 'counts', 'first_seen', 'last_seen']
    list_filter = ['date']
    readonly_fields = [f.name for f in Summary._meta.fields]


@admin.register(Run)
class RunAdmin(ReadOnlyAdmin):
    list_display = ['id', 'date', 'started_at', 'finished_at', 'trigger', 'status', 'row_count', 'limit_hit', 'records_link']
    list_filter = ['date', 'status', 'trigger']
    search_fields = ['message']
    readonly_fields = [f.name for f in Run._meta.fields] + ['records_link']
    exclude = ['records']

    @admin.display(description='本轮明细')
    def records_link(self, obj):
        return format_html('<a href="{}?runs__id__exact={}">查看本轮 {} 条记录</a>', reverse('admin:horgos_vehicleversion_changelist'), obj.pk, obj.row_count)


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ['date', 'article', 'run', 'publication_hold']
    readonly_fields = ['date', 'article', 'run']
    actions = ['withdraw', 'publish']
    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.publication_hold:
            obj.article.published = False
            obj.article.save(update_fields=['published', 'updated_at'])

    @admin.action(description='撤回并暂停自动发布', permissions=['change'])
    def withdraw(self, request, queryset):
        with transaction.atomic():
            for obj in queryset.select_related('article'):
                obj.publication_hold = True
                obj.save(update_fields=['publication_hold'])
                obj.article.published = False
                obj.article.save(update_fields=['published', 'updated_at'])

    @admin.action(description='发布已校验日报', permissions=['change'])
    def publish(self, request, queryset):
        with transaction.atomic():
            for obj in queryset.select_related('run', 'article'):
                if obj.run.status != 'success':
                    self.message_user(request, '未通过校验的日报不可发布。', messages.ERROR)
                    continue
                obj.publication_hold = False
                obj.save(update_fields=['publication_hold'])
                obj.article.published = True
                obj.article.published_at = obj.article.published_at or timezone.now()
                obj.article.save(update_fields=['published', 'published_at', 'updated_at'])
