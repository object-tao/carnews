from difflib import SequenceMatcher
import re
from django.contrib import admin, messages
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from .models import Category, Question, Reference


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'order', 'enabled']
    list_editable = ['order', 'enabled']
    search_fields = ['name', 'description']
    list_filter = ['enabled']
    def get_readonly_fields(self, request, obj=None): return ['slug', 'updated_at'] if obj else ['updated_at']


class ReferenceInline(admin.TabularInline):
    model = Reference
    extra = 0


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ['question', 'category', 'visibility', 'featured', 'order', 'published_at', 'updated_at', 'preview_link']
    list_filter = ['category', 'countries', 'published', 'featured']
    search_fields = ['question', 'short_answer', 'body', 'alternative_questions']
    list_select_related = ['category']
    filter_horizontal = ['countries', 'related_routes', 'related_resources', 'related_questions']
    inlines = [ReferenceInline]
    readonly_fields = ['updated_at', 'preview_link']
    actions = ['publish', 'withdraw']
    fieldsets = [
        ('问答内容', {'fields': ['question', 'category', 'short_answer', 'body', 'scope', 'image', 'image_caption']}),
        ('主题与关联资料', {'fields': ['countries', 'related_routes', 'related_resources', 'related_questions', 'alternative_questions']}),
        ('作者与核对信息', {'fields': ['author', 'author_type', 'reviewer', 'reviewed_on']}),
        ('搜索设置', {'fields': ['slug', 'seo_title', 'seo_description', 'seo_keywords']}),
        ('发布设置', {'fields': ['published', 'published_at', 'featured', 'order', 'updated_at', 'preview_link']}),
        ('内部资料', {'fields': ['editorial_notes'], 'classes': ['collapse']}),
    ]

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (['slug'] if obj and obj.published_at else [])

    @admin.display(description='展示状态')
    def visibility(self, obj):
        if not obj.published: return '草稿 / 已撤回'
        if not obj.category.enabled: return '子栏目已停用'
        if not obj.published_at or obj.published_at > timezone.now(): return '待发布时间'
        return '已公开'

    @admin.display(description='预览')
    def preview_link(self, obj):
        if not obj or not obj.pk: return '保存后可预览'
        return format_html('<a href="{}" target="_blank" rel="noopener">预览问答 ↗</a>', reverse('faq-preview', args=[obj.pk]))

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if 'question' not in form.changed_data: return
        normalize = lambda value: re.sub(r'\W+', '', value).casefold()
        question = normalize(obj.question)
        similar = [other for other in Question.objects.exclude(pk=obj.pk).only('pk', 'question')[:2000]
                   if SequenceMatcher(None, question, normalize(other.question)).ratio() >= .72][:5]
        if similar:
            links = format_html_join('、', '<a href="{}">{}</a>', ((reverse('admin:faq_question_change', args=[other.pk]), other.question) for other in similar))
            self.message_user(request, format_html('已保存。发现相似问题，请核对是否需要合并：{}', links), messages.WARNING)

    @admin.action(description='发布所选问答', permissions=['change'])
    def publish(self, request, queryset):
        for obj in queryset:
            obj.published = True
            obj.save(update_fields=['published', 'published_at', 'updated_at'])
        self.message_user(request, '已设置发布；仅启用栏目内且到达发布时间的问答会公开。')

    @admin.action(description='撤回所选问答', permissions=['change'])
    def withdraw(self, request, queryset):
        queryset.update(published=False, updated_at=timezone.now())
        self.message_user(request, '已撤回，前台与站点地图将同步移除。')
