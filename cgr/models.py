from datetime import time
from django.db import models
from django.urls import reverse
from django.utils import timezone
from .catalog import COUNTRIES


class CollectorSettings(models.Model):
    enabled = models.BooleanField('启用每日自动采集', default=True)
    daily_time = models.TimeField('每日采集时间（北京时间）', default=time(3, 10))
    auto_publish = models.BooleanField('校验通过后自动发布', default=True)
    requested_at = models.DateTimeField('最近手动补采请求', null=True, blank=True, editable=False)
    handled_request_at = models.DateTimeField(null=True, editable=False)
    lease_token = models.CharField(max_length=36, blank=True, editable=False)
    lease_until = models.DateTimeField(null=True, editable=False)

    class Meta:
        verbose_name = verbose_name_plural = '采集任务设置'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self):
        return f'每日 {self.daily_time:%H:%M}（北京时间）'


class Checkpoint(models.Model):
    source_name = models.CharField('源站俄文名称', max_length=180, unique=True)
    name = models.CharField('中文展示名称', max_length=180)
    country = models.CharField('对接国家或地区（哈方）', max_length=8, choices=COUNTRIES, blank=True)
    node_type = models.CharField('节点类型', max_length=12, choices=[('land', '陆路口岸'), ('port', '港口')], default='land')
    enabled = models.BooleanField('纳入采集与发布', default=True)
    needs_review = models.BooleanField('新发现，待核对', default=False)
    article = models.ForeignKey('web.Article', verbose_name='关联口岸介绍', null=True, blank=True, on_delete=models.SET_NULL, related_name='cgr_checkpoints')

    class Meta:
        verbose_name = verbose_name_plural = '口岸与国家映射'
        ordering = ['country', 'pk']

    def __str__(self):
        return self.name


class CollectionRun(models.Model):
    started_at = models.DateTimeField('开始时间', default=timezone.now)
    finished_at = models.DateTimeField('完成时间', null=True)
    report_date = models.DateField('报告日期（北京时间）')
    trigger = models.CharField('触发方式', max_length=16, choices=[('scheduled', '定时采集'), ('manual', '手动补采')])
    status = models.CharField('结果', max_length=12, choices=[('running', '执行中'), ('success', '校验通过'), ('failed', '失败，未发布')], default='running')
    source_updated = models.CharField('源站更新时间（源站未注明时区）', max_length=80, blank=True)
    source_hash = models.CharField('原始页面 SHA256', max_length=64, blank=True)
    raw_path = models.CharField('原始页面私有归档', max_length=250, blank=True)
    row_count = models.PositiveIntegerField('口岸日期记录数', default=0)
    message = models.TextField('运行记录', blank=True)

    class Meta:
        verbose_name = verbose_name_plural = '采集运行日志'
        ordering = ['-started_at', '-pk']
        indexes = [models.Index(fields=['report_date', 'trigger', 'status'])]

    def __str__(self):
        return f'{self.report_date} · #{self.pk} · {self.get_status_display()}'


class Observation(models.Model):
    STATES = [('available', '有可预约名额'), ('full', '名额为零'), ('holiday', '源站标注休息日'), ('not_open', '尚未开放预约')]
    run = models.ForeignKey(CollectionRun, on_delete=models.CASCADE, related_name='observations')
    checkpoint = models.ForeignKey(Checkpoint, verbose_name='口岸', on_delete=models.PROTECT)
    day = models.DateField('预约日期（源站日历）')
    state = models.CharField('预约状态', max_length=16, choices=STATES)
    level = models.PositiveSmallIntegerField('源站色阶')
    quotas = models.JSONField('各 МРП 档位剩余名额', default=dict)

    class Meta:
        verbose_name = verbose_name_plural = '口岸预约明细'
        ordering = ['checkpoint_id', 'day']
        constraints = [models.UniqueConstraint(fields=['run', 'checkpoint', 'day'], name='cgr_unique_observation')]


class DailyReport(models.Model):
    date = models.DateField('报告日期', unique=True)
    run = models.ForeignKey(CollectionRun, verbose_name='已校验数据', on_delete=models.PROTECT)
    article = models.OneToOneField('web.Article', verbose_name='报告文章', on_delete=models.PROTECT, related_name='cgr_report')
    publication_hold = models.BooleanField('暂停此日报的自动发布（人工撤回）', default=False)

    class Meta:
        verbose_name = verbose_name_plural = '口岸日报'
        ordering = ['-date']

    def __str__(self):
        return f'{self.date} 哈萨克斯坦口岸预约日报'

    def get_absolute_url(self):
        return self.article.get_absolute_url()
