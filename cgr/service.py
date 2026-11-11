"""Collection, validation, immutable snapshots and atomic daily publication."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import gzip
import hashlib
import logging
import time
from urllib.request import Request, urlopen
from urllib.error import URLError
from uuid import uuid4
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from .catalog import COUNTRIES, SOURCE_URL
from .models import Checkpoint, CollectorSettings, CollectionRun, DailyReport, Observation
from .parser import SourceError, parse_calendar

BEIJING = ZoneInfo('Asia/Shanghai')
logger = logging.getLogger(__name__)


def fetch_source():
    for attempt in range(3):
        try:
            request = Request(SOURCE_URL, headers={'User-Agent': 'Kunteng-Border-Updates/1.0 (+https://truck.diwuzhou.cn/contact/)', 'Accept-Language': 'ru', 'Cache-Control': 'no-cache'})
            with urlopen(request, timeout=35) as response:
                if not response.url.startswith('https://cgr.qoldau.kz/'):
                    raise SourceError('源站跳转至未配置的数据源')
                if int(response.headers.get('Age', '0')) > 0:
                    raise SourceError('源站返回缓存响应，暂停发布')
                data = response.read(4 * 1024 * 1024 + 1)
            if len(data) > 4 * 1024 * 1024:
                raise SourceError('源站页面超出采集大小限制')
            return data.decode('utf-8-sig')
        except (URLError, TimeoutError, OSError):
            if attempt == 2:
                raise SourceError('源站网络连接失败，已重试三次') from None
            time.sleep(3 * (attempt + 1))


def _due(config, now):
    """Minute timer polls a DB-configured Beijing schedule; manual requests have priority."""
    if config.requested_at and (not config.handled_request_at or config.requested_at > config.handled_request_at):
        return 'manual', config.requested_at
    local = now.astimezone(BEIJING)
    if not config.enabled or local.time().replace(tzinfo=None) < config.daily_time:
        return None, None
    runs = CollectionRun.objects.filter(report_date=local.date(), trigger='scheduled')
    if runs.filter(status='success').exists() or runs.count() >= 3:
        return None, None
    latest = runs.first()
    if latest and (latest.finished_at or latest.started_at) > now - timedelta(minutes=10):
        return None, None
    return 'scheduled', None


def collect(*, scheduled=False, html=None, now=None):
    now = now or timezone.now()
    config, _ = CollectorSettings.objects.get_or_create(pk=1)
    token = str(uuid4())
    claimed = CollectorSettings.objects.filter(pk=1).filter(
        Q(lease_until__isnull=True) | Q(lease_until__lte=now)
    ).update(lease_token=token, lease_until=now + timedelta(minutes=15))
    if not claimed:
        return None
    run = None
    try:
        config.refresh_from_db()
        # A process killed by the OS cannot leave an eternal "running" status.
        CollectionRun.objects.filter(status='running', started_at__lt=now-timedelta(minutes=15)).update(
            status='failed', finished_at=now, message='前次进程中断或超时，已释放任务锁。')
        trigger, requested = _due(config, now) if scheduled else ('manual', config.requested_at)
        if not trigger:
            return None
        run = CollectionRun.objects.create(report_date=now.astimezone(BEIJING).date(), started_at=now, trigger=trigger)
        if requested:
            CollectorSettings.objects.filter(pk=1, lease_token=token).update(handled_request_at=requested)
        source = fetch_source() if html is None else html
        finished = timezone.now() if html is None else now
        if finished.astimezone(BEIJING).date() != run.report_date or not timedelta(0) <= finished-now <= timedelta(minutes=5):
            raise SourceError('本轮采集跨日或耗时异常，暂停发布')
        raw = source.encode('utf-8')
        run.source_hash = hashlib.sha256(raw).hexdigest()
        run.raw_path = f'cgr/raw/{run.report_date:%Y/%m}/{run.pk}-{token}.html.gz'
        path = settings.DATA_DIR / run.raw_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(raw))
        run.save(update_fields=['source_hash', 'raw_path'])
        parsed = parse_calendar(source, run.report_date)
        run.source_updated = parsed['source_updated']
        run.save(update_fields=['source_updated'])
        known = {obj.source_name: obj for obj in Checkpoint.objects.all()}
        if not known:
            raise SourceError('尚未初始化口岸目录，请先运行 seed_cgr')
        unknown = []
        allowed_countries = dict(COUNTRIES)
        for row in parsed['rows']:
            if row['name'] not in known:
                Checkpoint.objects.get_or_create(source_name=row['name'], defaults={
                    'name': row['name'], 'country': row['country'] if row['country'] in allowed_countries else '',
                    'enabled': False, 'needs_review': True,
                    'node_type': 'port' if row['country'] == 'xa' else 'land'})
                unknown.append(row['name'])
        if unknown or Checkpoint.objects.filter(needs_review=True).exists():
            raise SourceError('发现待核对口岸，请在“口岸与国家映射”确认名称、国家及启用状态后取消待核对标记。')
        expected = {name for name, obj in known.items() if obj.enabled}
        present = {row['name'] for row in parsed['rows']}
        if not expected or expected - present:
            raise SourceError('源站缺少已启用口岸：' + '、'.join(sorted(expected - present)))
        observations = []
        for row in parsed['rows']:
            obj = known[row['name']]
            if not obj.enabled:
                continue
            if obj.country not in allowed_countries or row['country'] != obj.country:
                raise SourceError(f'{obj.name}：源站国家归属与后台映射不一致')
            observations.extend(Observation(first_run=run, checkpoint=obj, **cell) for cell in row['cells'])
        with transaction.atomic():
            config.refresh_from_db()
            if config.lease_token != token or config.lease_until <= finished: raise SourceError('任务锁已失效，本轮不写入')
            from .storage import attach_observations
            attach_observations(run, observations)
            run.row_count = len(observations)
            run.status = 'success'
            run.finished_at = finished
            run.message = f'校验通过：{len(expected)} 个节点，{(parsed["end"]-parsed["start"]).days+1} 天，{len(observations)} 条记录。'
            run.save()
            # Respect an administrator pausing publication while a network fetch is in progress.
            config.refresh_from_db()
            report = publish_report(run, auto_publish=config.auto_publish)
            run.message += ' 日报已发布。' if report.article.published else ' 日报已保存为草稿或保持撤回状态。'
            run.save(update_fields=['message'])
        return run
    except Exception as exc:
        if run:
            message = str(exc) if isinstance(exc, SourceError) else f'采集处理失败（{type(exc).__name__}），请检查服务日志。'
            if not isinstance(exc, SourceError):
                logger.exception('CGR processing failure for run %s', run.pk)
            # Never reuse a success value left on the Python instance after transaction rollback.
            CollectionRun.objects.filter(pk=run.pk).update(status='failed', finished_at=timezone.now(), message=message)
            run.refresh_from_db()
            return run
        raise
    finally:
        CollectorSettings.objects.filter(pk=1, lease_token=token).update(lease_token='', lease_until=None)


def compare_previous(run, observations):
    previous = CollectionRun.objects.filter(status='success', started_at__lt=run.started_at).exclude(pk=run.pk).first()
    if not previous:
        return '本期为首次有效采集，尚无历史快照可比较。'
    old = {(o.checkpoint_id, o.day): o for o in previous.observations.all()}
    comparable = changed = 0
    for current in observations:
        before = old.get((current.checkpoint_id, current.day))
        if not before:
            continue
        for tier in current.quotas.keys() & before.quotas.keys():
            comparable += 1
            changed += int(current.quotas[tier] != before.quotas[tier])
    if not comparable:
        return '与上一有效采集没有可比较的同日同档位名额。'
    return f'与上一有效采集（北京时间 {previous.started_at.astimezone(BEIJING):%Y-%m-%d %H:%M}）比较：{comparable} 项相同口岸、预约日期和档位的记录中，{changed} 项名额发生变化。不同日期、未开放及休息日不按零名额参与比较。'


def publish_report(run, *, auto_publish):
    from web.models import Article, Country
    observations = list(run.observations.select_related('checkpoint').order_by('checkpoint_id', 'day'))
    nodes = {o.checkpoint_id: o.checkpoint for o in observations}
    days = sorted({o.day for o in observations})
    labels = dict(COUNTRIES)
    title = f'哈萨克斯坦口岸预约日报：中哈、哈俄及周边口岸（{run.report_date:%Y年%m月%d日}）'
    summary = f'{run.report_date:%Y年%m月%d日}哈萨克斯坦与中国、俄罗斯及周边国家口岸预约数据，覆盖{len(nodes)}个节点；汇总{days[0]}至{days[-1]}源站预约情况及国家方向变化。预约名额不代表现场排队时长。'
    body = [f'## 本期采集范围\n\n本期共记录 **{len(nodes)} 个口岸及港口节点、{len(days)} 个预约日期**。',
            f'数据采集时间：北京时间 {run.started_at.astimezone(BEIJING):%Y-%m-%d %H:%M}。源站预约区块更新时间：{run.source_updated}（源站未注明时区）。',
            f'预约日历覆盖 **{days[0]} 至 {days[-1]}**，表示本次采集时看到的未来预约安排。报告日期采用北京时间，预约日期保留源站日历口径。',
            '## 与上一有效采集比较\n\n' + compare_previous(run, observations),
            '## 各国家方向\n\n| 对接国家或地区 | 节点数 |\n| --- | ---: |']
    for code, label in COUNTRIES:
        count = sum(node.country == code for node in nodes.values())
        if count:
            body.append(f'| {label} | {count} |')
    today_cells = [o for o in observations if o.day == run.report_date]
    if today_cells:
        body += ['\n## 采集当日预约概况\n\n以下按报告日期对应的预约日统计节点状态，各列互斥；名额不代表排队车辆数。\n\n| 国家 / 地区 | 有名额节点 | 零名额节点 | 休息日节点 | 未开放节点 |\n| --- | ---: | ---: | ---: | ---: |']
        for code, label in COUNTRIES:
            cells = [o for o in today_cells if o.checkpoint.country == code]
            if cells:
                values = [sum(o.state == state for o in cells) for state in ['available', 'full', 'holiday', 'not_open']]
                body.append('| ' + label + ' | ' + ' | '.join(str(v) for v in values) + ' |')
    body += ['\n## 数据如何使用\n\n- **有可预约名额**：至少一个源站预约档位有剩余名额。\n- **名额为零**：该日期源站公布的档位均为零，不代表口岸关闭或现场排队人数。\n- **休息日**与**尚未开放预约**分别标注，名额留空。\n- **МРП** 沿用源站预约档位单位；名额以“个”计，不是运费、吨位或通关时长。\n- 中文名称用于检索，俄文原名用于核对；具体预约与通行安排以源站和口岸通知为准。',
             f'\n来源：[CarGoRuqsat 官方统计]({SOURCE_URL})。原始页面与采集校验记录已归档。']
    defaults = dict(title=title, kind='news', category='口岸动态', summary=summary, body='\n\n'.join(body[:4])+'\n\n'+'\n'.join(body[4:]),
                    body_format='markdown', source=SOURCE_URL, seo_title=title,
                    seo_keywords='哈萨克斯坦口岸,中哈口岸,哈俄口岸,口岸预约,巴克图,都拉塔,霍尔果斯,俄罗斯口岸,口岸动态',
                    author='深圳昆腾口岸数据整理', reviewed_on=run.report_date)
    article, created = Article.objects.get_or_create(slug=f'cgr-border-report-{run.report_date}', defaults=defaults)
    report, _ = DailyReport.objects.get_or_create(date=run.report_date, defaults={'run': run, 'article': article})
    if report.article_id != article.pk:
        raise SourceError('日报文章关联异常')
    for field, value in defaults.items():
        setattr(article, field, value)
    article.published = auto_publish and not report.publication_hold
    if article.published:
        if not article.published_at:
            article.published_at = run.started_at
    article.save()
    tags = []
    for name, slug in [('哈萨克斯坦', 'kazakhstan')] + [(labels[code], 'cgr-'+code) for code in labels if any(n.country == code for n in nodes.values())]:
        tag = Country.objects.filter(name=name).first()
        if not tag:
            tag = Country.objects.create(name=name, slug=slug)
        tags.append(tag)
    article.countries.set(tags)
    article.related_resources.set([n.article_id for n in nodes.values() if n.article_id])
    report.run = run
    report.save(update_fields=['run'])
    return report
