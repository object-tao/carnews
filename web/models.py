from django.db import models
from django.urls import reverse
from django.core.validators import FileExtensionValidator

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

class Route(models.Model):
    REGIONS = [('asia','中亚'),('europe','欧洲及英国'),('southeast','东南亚'),('russia','俄罗斯与白俄罗斯')]
    title = models.CharField('线路名称', max_length=120)
    slug = models.SlugField('网址标识（英文）', unique=True)
    region = models.CharField('业务区域', max_length=20, choices=REGIONS)
    countries = models.CharField('覆盖国家', max_length=500)
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
    category = models.CharField('分类', max_length=60, default='运输知识')
    summary = models.CharField('摘要', max_length=300)
    body = models.TextField('正文', help_text='纯文本分段，自动安全排版。')
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
