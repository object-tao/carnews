from datetime import time
from django.db import models
from django.utils import timezone


class Settings(models.Model):
    enabled = models.BooleanField('启用定时采集', default=True)
    daily_time = models.TimeField('采集时间（北京时间）', default=time(23, 50))
    auto_publish = models.BooleanField('校验后自动发布', default=True)
    requested_at = models.DateTimeField('手动补采请求', null=True, blank=True, editable=False)
    handled_request_at = models.DateTimeField(null=True, editable=False)
    lease_token = models.CharField(max_length=36, blank=True, editable=False)
    lease_until = models.DateTimeField(null=True, editable=False)

    class Meta:
        verbose_name = verbose_name_plural = '霍尔果斯采集设置'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self): return f'每天 {self.daily_time:%H:%M}（北京时间）'


class Summary(models.Model):
    date = models.DateField('业务日期', db_index=True)
    fingerprint = models.CharField(max_length=64, unique=True, editable=False)
    counts = models.JSONField('源站当日汇总')
    first_seen = models.DateTimeField('首次采集')
    last_seen = models.DateTimeField('最近确认')

    class Meta:
        verbose_name = verbose_name_plural = '霍尔果斯汇总版本'
        ordering = ['-date', '-last_seen']


class Vehicle(models.Model):
    identity = models.CharField(max_length=64, unique=True, editable=False)
    kind = models.CharField('源站类型', max_length=12, choices=[('commercial', '整车'), ('heavy', '重车')])
    number = models.CharField('业务编号', max_length=100, db_index=True)
    occurred_at = models.DateTimeField('业务时间（北京时间）', db_index=True)
    company = models.CharField('企业', max_length=200, blank=True)
    status = models.CharField('状态', max_length=80)
    first_seen = models.DateTimeField('首次采集')
    last_seen = models.DateTimeField('最近确认')

    class Meta:
        verbose_name = verbose_name_plural = '霍尔果斯车辆明细（仅后台）'
        ordering = ['-occurred_at', '-pk']

    def __str__(self): return f'{self.get_kind_display()} / {self.number}'


class VehicleVersion(models.Model):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name='versions', verbose_name='业务记录')
    fingerprint = models.CharField(max_length=64, unique=True, editable=False)
    company = models.CharField('企业', max_length=200, blank=True)
    status = models.CharField('状态', max_length=80)
    first_seen = models.DateTimeField('首次采集')
    last_seen = models.DateTimeField('最近确认')

    class Meta:
        verbose_name = verbose_name_plural = '霍尔果斯明细变更版本'


class Run(models.Model):
    started_at = models.DateTimeField('采集开始', default=timezone.now)
    finished_at = models.DateTimeField('采集完成', null=True)
    date = models.DateField('本期业务日期', db_index=True)
    trigger = models.CharField('触发方式', max_length=12, choices=[('scheduled', '定时'), ('manual', '手动')])
    status = models.CharField('结果', max_length=12, choices=[('running', '执行中'), ('success', '校验通过'), ('failed', '失败')], default='running')
    summary = models.ForeignKey(Summary, null=True, on_delete=models.PROTECT, verbose_name='同轮汇总版本')
    records = models.ManyToManyField(VehicleVersion, related_name='runs', blank=True)
    row_count = models.PositiveIntegerField('本轮当日明细数', default=0)
    skipped_count = models.PositiveIntegerField('非当日记录数', default=0)
    limit_hit = models.BooleanField('源接口返回达到上限', default=False)
    raw_path = models.CharField('原始响应私有归档', max_length=250, blank=True)
    message = models.TextField('执行记录', blank=True)

    class Meta:
        verbose_name = verbose_name_plural = '霍尔果斯采集日志'
        ordering = ['-started_at', '-pk']
        indexes = [models.Index(fields=['date', 'trigger', 'status'])]

    def __str__(self): return f'{self.date} / #{self.pk} / {self.get_status_display()}'


class Report(models.Model):
    date = models.DateField('报告日期', unique=True)
    run = models.ForeignKey(Run, on_delete=models.PROTECT, verbose_name='同轮已校验数据')
    article = models.OneToOneField('web.Article', on_delete=models.PROTECT, related_name='horgos_report', verbose_name='报告文章')
    publication_hold = models.BooleanField('暂停自动发布（人工撤回）', default=False)

    class Meta:
        verbose_name = verbose_name_plural = '霍尔果斯日报'
        ordering = ['-date']

    def __str__(self): return f'{self.date} 霍尔果斯车辆日报'
