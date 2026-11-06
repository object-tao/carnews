from django.db import models
from django.urls import reverse
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal

class SiteSettings(models.Model):
    brand = models.CharField('品牌名称', max_length=80, default='深圳昆腾')
    company = models.CharField('公司主体', max_length=120, default='深圳市昆腾电子商务有限公司')
    introduction = models.TextField('公司介绍', default='深圳昆腾面向中国客户提供国际公路货物整车运输服务，服务区域包括中亚、东南亚、欧洲及英国、俄罗斯与白俄罗斯。具体承运方案请结合货物与起讫地咨询。')
    phone = models.CharField('咨询电话', max_length=40, blank=True)
    wechat = models.CharField('微信号', max_length=80, blank=True)
    qr = models.FileField('微信二维码（PNG/JPG）', upload_to='contact/', blank=True, validators=[FileExtensionValidator(['png','jpg','jpeg','webp'])])
    icp = models.CharField('备案号', max_length=80, blank=True)
    class Meta:
        verbose_name = verbose_name_plural = '网站设置'
    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
    def __str__(self): return self.brand


class Country(models.Model):
    name = models.CharField('国家名称', max_length=80, unique=True)
    slug = models.SlugField('网址标识', unique=True)
    order = models.PositiveIntegerField('排序', default=0)
    class Meta:
        ordering = ['order', 'name']
        verbose_name = verbose_name_plural = '国家与地区'
    def __str__(self): return self.name

class ResourceType(models.Model):
    name = models.CharField('资料类型名称', max_length=80, unique=True)
    slug = models.SlugField('类型标识', unique=True, help_text='使用英文；routes 为共用线路资料保留，不可使用。')
    order = models.PositiveIntegerField('排序', default=0)
    class Meta:
        ordering = ['order', 'pk']
        verbose_name = verbose_name_plural = '资源类型'
    def clean(self):
        if self.slug == 'routes':
            raise ValidationError({'slug': 'routes 已由共用运输线路使用，请选择其他标识。'})
    def __str__(self): return self.name

class Route(models.Model):
    REGIONS = [('asia','中亚'),('europe','欧洲及英国'),('southeast','东南亚'),('russia','俄罗斯与白俄罗斯')]
    title = models.CharField('线路名称', max_length=120)
    slug = models.SlugField('网址标识（英文）', unique=True)
    region = models.CharField('业务区域', max_length=20, choices=REGIONS)
    countries = models.CharField('覆盖国家说明', max_length=500)
    country_tags = models.ManyToManyField(Country, blank=True, verbose_name='关联国家', related_name='routes')
    summary = models.CharField('简要介绍', max_length=300)
    body = models.TextField('线路说明', help_text='使用纯文本，可分段；请注明时效及承运条件。')
    published = models.BooleanField('公开展示', default=False)
    order = models.PositiveIntegerField('排序', default=0)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    class Meta:
        ordering = ['order','title']
        verbose_name = verbose_name_plural = '运输线路'
    def __str__(self): return self.title
    def get_absolute_url(self): return reverse('route', args=[self.slug])

class Article(models.Model):
    KINDS = [('news','行业资讯'),('resources','资源库')]
    title = models.CharField('标题', max_length=180)
    slug = models.SlugField('网址标识（英文）', unique=True)
    kind = models.CharField('栏目', max_length=20, choices=KINDS)
    category = models.CharField('内容分类', max_length=60, default='运输知识')
    resource_type = models.ForeignKey(ResourceType, null=True, blank=True, on_delete=models.PROTECT, verbose_name='资料类型', related_name='articles')
    countries = models.ManyToManyField(Country, blank=True, verbose_name='关联国家', related_name='articles')
    related_routes = models.ManyToManyField(Route, blank=True, verbose_name='关联线路', related_name='resources')
    related_resources = models.ManyToManyField('self', blank=True, symmetrical=False, verbose_name='关联口岸、车型等资料')
    location = models.CharField('位置或连接区域', max_length=300, blank=True)
    specifications = models.TextField('参考尺寸、载重等参数', blank=True)
    access_info = models.TextField('开放、通行与装卸信息', blank=True)
    requirements = models.TextField('单证与操作要求', blank=True)
    restrictions = models.TextField('限制条件与注意事项', blank=True)
    summary = models.CharField('摘要', max_length=300)
    body = models.TextField('正文', help_text='可选纯文本或 Markdown；支持标题、表格和列表。')
    body_format = models.CharField('正文格式', max_length=12, choices=[('text','纯文本'),('markdown','Markdown')], default='text')
    reviewed_on = models.DateField('资料核对日期（非实时通关确认）', null=True, blank=True)
    original_source = models.TextField('原始资料（仅后台）', blank=True)
    editorial_notes = models.TextField('校订记录（仅后台）', blank=True)
    image = models.ImageField('资料图片', upload_to='resource-images/', blank=True, validators=[FileExtensionValidator(['png','jpg','jpeg','webp'])])
    image_caption = models.CharField('图片说明', max_length=500, blank=True)
    image_note = models.TextField('图片性质与使用说明', blank=True)
    image_creator = models.CharField('图片作者', max_length=300, blank=True)
    image_source = models.URLField('图片来源页', max_length=600, blank=True)
    image_license = models.CharField('图片许可', max_length=80, blank=True)
    image_license_url = models.URLField('许可链接', blank=True)
    image_taken_on = models.CharField('拍摄日期', max_length=40, blank=True)
    author = models.CharField('作者或审核人', max_length=80, default='深圳昆腾编辑部')
    source = models.URLField('参考来源链接', blank=True)
    attachment = models.FileField('下载附件（PDF/DOCX/XLSX）', upload_to='resources/', blank=True, validators=[FileExtensionValidator(['pdf','docx','xlsx'])])
    published = models.BooleanField('发布', default=False)
    published_at = models.DateTimeField('发布时间', null=True, blank=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    class Meta:
        ordering = ['-published_at','-pk']
        verbose_name = verbose_name_plural = '资讯与资源'
    def __str__(self): return self.title
    def get_absolute_url(self): return reverse('article', args=[self.slug])

class FreightRate(models.Model):
    route = models.ForeignKey(Route, on_delete=models.PROTECT, verbose_name='关联线路', related_name='freight_rates')
    slug = models.SlugField('网址标识', unique=True)
    origin = models.CharField('装货地', max_length=160)
    destination = models.CharField('卸货地', max_length=160)
    vehicle = models.CharField('车型及规格', max_length=160)
    cargo = models.CharField('适用货物与装载条件', max_length=300)
    price_min = models.DecimalField('参考价格（下限或单价）', max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    price_max = models.DecimalField('价格上限（区间报价时填写）', max_digits=14, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal('0.01'))])
    currency = models.CharField('币种', max_length=3, choices=[('CNY','人民币 CNY'),('USD','美元 USD'),('EUR','欧元 EUR'),('RUB','俄罗斯卢布 RUB'),('KZT','哈萨克斯坦坚戈 KZT')], default='CNY')
    unit = models.CharField('计价单位', max_length=40, default='车')
    terms = models.TextField('费用范围与适用条件', help_text='请明确包含、不含项目及附加费触发条件。')
    source = models.CharField('价格来源说明', max_length=300)
    source_url = models.URLField('来源链接', blank=True)
    valid_from = models.DateField('有效期开始')
    valid_until = models.DateField('有效期结束（含当日）')
    published = models.BooleanField('发布', default=False)
    published_at = models.DateTimeField('发布时间', null=True, blank=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    class Meta:
        ordering = ['-updated_at', '-pk']
        verbose_name = verbose_name_plural = '参考运价'
        constraints = [
            models.CheckConstraint(condition=models.Q(price_min__gt=0), name='rate_price_positive'),
            models.CheckConstraint(condition=models.Q(price_max__isnull=True) | models.Q(price_max__gte=models.F('price_min')), name='rate_price_range'),
            models.CheckConstraint(condition=models.Q(valid_until__gte=models.F('valid_from')), name='rate_valid_dates'),
        ]
    def clean(self):
        errors = {}
        if self.price_max is not None and self.price_min is not None and self.price_max < self.price_min:
            errors['price_max'] = '上限不能小于下限。'
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            errors['valid_until'] = '结束日期不能早于开始日期。'
        if errors: raise ValidationError(errors)
    @property
    def validity(self):
        if not self.valid_from or not self.valid_until: return 'pending'
        today = timezone.localdate()
        if today < self.valid_from: return 'upcoming'
        if today > self.valid_until: return 'expired'
        return 'valid'
    @property
    def validity_label(self):
        return {'pending':'待填写有效期','upcoming':'尚未生效', 'expired':'已过期', 'valid':'有效期内'}[self.validity]
    def __str__(self): return f'{self.origin} → {self.destination} / {self.vehicle}'
    def get_absolute_url(self): return reverse('freight-rate', args=[self.slug])

class ArticleReference(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='references')
    title = models.CharField('来源名称', max_length=300)
    url = models.URLField('来源链接', max_length=1000)
    note = models.CharField('资料日期与使用范围', max_length=500, blank=True)
    class Meta:
        ordering = ['pk']
        verbose_name = verbose_name_plural = '核对来源'
    def __str__(self): return self.title
