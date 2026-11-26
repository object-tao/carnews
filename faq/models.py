from uuid import uuid4
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Category(models.Model):
    name = models.CharField('子栏目名称', max_length=80)
    slug = models.SlugField('网址标识', unique=True, blank=True, help_text='留空自动生成；创建后固定，修改名称不会改变网址。')
    description = models.CharField('栏目说明', max_length=600, blank=True)
    seo_title = models.CharField('SEO 标题', max_length=180, blank=True)
    seo_description = models.CharField('SEO 摘要', max_length=300, blank=True)
    order = models.PositiveIntegerField('排序（越小越靠前）', default=0)
    enabled = models.BooleanField('启用', default=True, help_text='停用后，该栏目及其问答不在前台展示。')
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        ordering = ['order', 'pk']
        verbose_name = verbose_name_plural = 'FAQ 子栏目'

    def __str__(self): return self.name
    def get_absolute_url(self): return reverse('faq-category', args=[self.slug])

    def clean(self):
        if self.pk and Category.objects.filter(pk=self.pk).exclude(slug=self.slug).exists():
            raise ValidationError({'slug': '已创建栏目的网址固定，请只修改名称。'})

    def save(self, *args, **kwargs):
        if not self.slug: self.slug = 'category-' + uuid4().hex[:12]
        super().save(*args, **kwargs)


class QuestionQuerySet(models.QuerySet):
    def public(self):
        return self.filter(published=True, published_at__lte=timezone.now(), category__enabled=True)


class Question(models.Model):
    question = models.CharField('问题标题', max_length=250)
    slug = models.SlugField('网址标识', unique=True, blank=True, max_length=180, help_text='留空自动生成；首次发布后固定，修改问题标题不会改变网址。')
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='questions', verbose_name='所属子栏目')
    short_answer = models.TextField('简明回答', max_length=1200, help_text='建议先用 2—4 句话直接回答问题。')
    body = models.TextField('详细说明', blank=True, help_text='选填，支持 Markdown 标题、步骤、列表和表格。')
    scope = models.TextField('适用条件', blank=True, help_text='可填写适用国家、货物条件、例外和时效范围。')
    alternative_questions = models.TextField('其他问法', blank=True, help_text='仅用于站内搜索，每行一种问法；同一问题无需重复建页。')
    countries = models.ManyToManyField('web.Country', blank=True, verbose_name='适用国家', related_name='faqs')
    related_routes = models.ManyToManyField('web.Route', blank=True, verbose_name='关联线路', related_name='faqs')
    related_resources = models.ManyToManyField('web.Article', blank=True, verbose_name='关联口岸、车型及知识文章', related_name='faqs')
    related_questions = models.ManyToManyField('self', symmetrical=False, blank=True, related_name='referenced_by', verbose_name='相关问题')
    image = models.ImageField('说明图片', upload_to='faq-images/', blank=True, validators=[FileExtensionValidator(['png','jpg','jpeg','webp'])])
    image_caption = models.CharField('图片说明', max_length=500, blank=True)
    author = models.CharField('作者', max_length=80, default='深圳昆腾编辑部', blank=True)
    author_type = models.CharField('作者身份', max_length=12, choices=[('Organization', '机构'), ('Person', '个人')], default='Organization')
    reviewer = models.CharField('审核人', max_length=80, blank=True)
    reviewed_on = models.DateField('内容核对日期', null=True, blank=True)
    seo_title = models.CharField('SEO 标题', max_length=180, blank=True, help_text='留空使用问题标题。')
    seo_description = models.CharField('SEO 摘要', max_length=300, blank=True, help_text='留空使用简明回答的前 160 字。')
    seo_keywords = models.CharField('关键词', max_length=500, blank=True, help_text='以中文或英文逗号分隔。')
    editorial_notes = models.TextField('内部备注（不公开）', blank=True)
    featured = models.BooleanField('推荐问题', default=False)
    order = models.PositiveIntegerField('推荐排序（越小越靠前）', default=0)
    published = models.BooleanField('发布', default=False)
    published_at = models.DateTimeField('发布时间', null=True, blank=True, help_text='发布时留空则自动填写；未来时间到达后才公开。撤回不会清除此时间。')
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    objects = QuestionQuerySet.as_manager()

    class Meta:
        ordering = ['-updated_at', '-pk']
        verbose_name = verbose_name_plural = 'FAQ 问答'

    def __str__(self): return self.question
    def get_absolute_url(self): return reverse('faq-detail', args=[self.slug])

    @property
    def description(self): return self.seo_description or ' '.join(self.short_answer.split())[:160]

    def clean(self):
        if not self.question.strip(): raise ValidationError({'question': '请填写问题。'})
        if not self.short_answer.strip(): raise ValidationError({'short_answer': '请填写简明回答。'})
        if self.pk and Question.objects.filter(pk=self.pk, published_at__isnull=False).exclude(slug=self.slug).exists():
            raise ValidationError({'slug': '已发布问答的网址固定，修改标题不会改变网址。'})

    def save(self, *args, **kwargs):
        if not self.slug: self.slug = 'q-' + uuid4().hex[:16]
        if self.published and not self.published_at: self.published_at = timezone.now()
        super().save(*args, **kwargs)


class Reference(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='references', verbose_name='问题')
    title = models.CharField('来源名称', max_length=300)
    url = models.URLField('来源链接', max_length=1000)
    note = models.CharField('来源日期与适用范围', max_length=500, blank=True)

    class Meta:
        ordering = ['pk']
        verbose_name = verbose_name_plural = '参考来源'

    def __str__(self): return self.title
