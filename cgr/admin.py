from django.contrib import admin, messages
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from .models import Checkpoint, CollectorSettings, CollectionRun, DailyReport, Observation


@admin.register(CollectorSettings)
class CollectorSettingsAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'enabled', 'auto_publish', 'requested_at', 'request_state']
    readonly_fields = ['requested_at', 'request_state']
    fields = ['enabled', 'daily_time', 'auto_publish', 'requested_at', 'request_state']
    actions = ['request_collection']

    def has_add_permission(self, request):
        return not CollectorSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='手动任务状态')
    def request_state(self, obj):
        if obj.lease_until and obj.lease_until > timezone.now():
            return '正在执行采集'
        if obj.requested_at and (not obj.handled_request_at or obj.requested_at > obj.handled_request_at):
            return '等待执行（通常一分钟内启动）'
        return '无待执行请求；运行结果请查看“采集运行日志”'

    @admin.action(description='立即补采一次（后台执行）', permissions=['change'])
    def request_collection(self, request, queryset):
        queryset.update(requested_at=timezone.now())
        self.message_user(request, '已提交补采请求，通常一分钟内执行。请在采集运行日志查看结果。')


@admin.register(Checkpoint)
class CheckpointAdmin(admin.ModelAdmin):
    list_display = ['name', 'country', 'node_type', 'enabled', 'needs_review', 'article']
    list_filter = ['country', 'enabled', 'needs_review', 'node_type']
    search_fields = ['name', 'source_name']
    autocomplete_fields = ['article']


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False
    def has_change_permission(self, request, obj=None): return False


@admin.register(CollectionRun)
class CollectionRunAdmin(ReadOnlyAdmin):
    list_display = ['id', 'report_date', 'started_at', 'finished_at', 'trigger', 'status', 'row_count']
    list_filter = ['status', 'trigger', 'report_date']
    search_fields = ['message', 'source_hash']
    readonly_fields = [field.name for field in CollectionRun._meta.fields]


@admin.register(Observation)
class ObservationAdmin(ReadOnlyAdmin):
    list_display = ['checkpoint', 'day', 'state', 'quotas', 'level', 'run']
    list_filter = ['checkpoint__country', 'state', 'day']
    search_fields = ['checkpoint__name', 'checkpoint__source_name']
    list_select_related = ['checkpoint', 'run']
    readonly_fields = [field.name for field in Observation._meta.fields]


@admin.register(DailyReport)
class DailyReportAdmin(admin.ModelAdmin):
    list_display = ['date', 'published', 'publication_hold', 'run', 'preview_link']
    list_filter = ['publication_hold', 'article__published', 'date']
    readonly_fields = ['date', 'run', 'article', 'preview_link']
    actions = ['publish', 'withdraw']

    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False

    @admin.display(description='已发布', boolean=True)
    def published(self, obj): return obj.article.published

    @admin.display(description='预览与下载')
    def preview_link(self, obj):
        return format_html('<a href="{}?preview=1">预览日报 / 下载清单</a>', reverse('cgr-preview', args=[obj.pk]))

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.publication_hold:
            obj.article.published = False
            obj.article.save(update_fields=['published', 'updated_at'])

    @admin.action(description='发布所选已校验日报', permissions=['change'])
    def publish(self, request, queryset):
        from django.db import transaction
        with transaction.atomic():
            for obj in queryset.select_related('run', 'article'):
                if obj.run.status != 'success':
                    self.message_user(request, '存在未通过校验的数据，已跳过。', messages.ERROR)
                    continue
                obj.publication_hold = False
                obj.save(update_fields=['publication_hold'])
                obj.article.published = True
                obj.article.published_at = obj.article.published_at or timezone.now()
                obj.article.save(update_fields=['published', 'published_at', 'updated_at'])
        self.message_user(request, '已发布所选有效日报。')

    @admin.action(description='撤回并暂停所选日报自动发布', permissions=['change'])
    def withdraw(self, request, queryset):
        from django.db import transaction
        with transaction.atomic():
            for obj in queryset.select_related('article'):
                obj.publication_hold = True
                obj.save(update_fields=['publication_hold'])
                obj.article.published = False
                obj.article.save(update_fields=['published', 'updated_at'])
        self.message_user(request, '已撤回；后续同日补采不会自动重新发布。')
