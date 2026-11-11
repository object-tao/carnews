from datetime import timedelta
from pathlib import Path
from uuid import uuid4
import gzip
import json
import logging
from django.conf import settings as django_settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from .client import BEIJING, CATEGORIES, FIELDS, SOURCE_URL, SourceError, digest, fetch, normalize
from .models import Settings, Run, Summary, Vehicle, VehicleVersion, Report

logger = logging.getLogger(__name__)


def due(config, now):
    if config.requested_at and (not config.handled_request_at or config.requested_at > config.handled_request_at):
        return 'manual', config.requested_at
    local = now.astimezone(BEIJING)
    if not config.enabled or local.time().replace(tzinfo=None) < config.daily_time: return None, None
    runs = Run.objects.filter(date=local.date(), trigger='scheduled')
    if runs.filter(status='success').exists() or runs.count() >= 3: return None, None
    previous = runs.first()
    if previous and (previous.finished_at or previous.started_at) > now-timedelta(minutes=2): return None, None
    return 'scheduled', None


def publish(run, auto_publish):
    from web.models import Article, Country
    counts = run.summary.counts
    title = f'霍尔果斯口岸车辆预约与放行日报（{run.date:%Y年%m月%d日}）'
    summary = f'{run.date:%Y年%m月%d日}霍尔果斯口岸车辆预约、放行与货类汇总，数据截至北京时间{run.finished_at.astimezone(BEIJING):%H:%M}，采用本轮源接口统计。'
    body = [f'## 本期概况\n\n本期为 **{run.date:%Y年%m月%d日}** 霍尔果斯口岸车辆数据汇总。',
            f'采集区间：北京时间 **{run.started_at.astimezone(BEIJING):%H:%M:%S}—{run.finished_at.astimezone(BEIJING):%H:%M:%S}**。以下汇总均来自这一轮源接口请求，代表截至采集时点的统计，不是完整全天最终结算。',
            '## 车辆预约与放行\n\n| 源站统计项目 | 数量 |\n| --- | ---: |']
    body[-1] += '\n' + '\n'.join(f'| {label} | {counts[key]} |' for key, label in FIELDS.items())
    body += ['\n## 货类统计\n\n| 源站货类 | 数量 |\n| --- | ---: |']
    body[-1] += '\n' + '\n'.join(f'| {name} | {counts["categories"][name]} |' for name in CATEGORIES)
    body += ['\n## 统计口径与使用说明\n\n- “整车”“重车”“自驾”“笼车”沿用源站分类；不同分类之间可能存在包含关系，不将各行简单相加。\n- 源站当日汇总与逐条明细是不同接口，本报告直接采用汇总接口，未用明细条数推算总量。\n- 明细接口每类最多提供最近 1000 条，因此已采明细不代表完整通行历史；本轮只归档北京时间当日业务记录。\n- 本报告不据此推算排队人数、等待时长或通关承诺。',
             f'数据来源：[霍尔果斯口岸数据接口]({SOURCE_URL}/postNumNow)。按实际采集日期和时点标注，历史报告保留各自统计口径。']
    defaults = dict(title=title, seo_title=title, summary=summary, body='\n\n'.join(body), body_format='markdown',
                    kind='news', category='口岸动态', source=SOURCE_URL+'/postNumNow',
                    seo_keywords='霍尔果斯口岸,霍尔果斯日报,口岸车辆放行,整车预约,重车放行,口岸货类统计,中哈运输',
                    author='深圳昆腾口岸数据整理', reviewed_on=run.date)
    article, _ = Article.objects.get_or_create(slug=f'horgos-border-report-{run.date}', defaults=defaults)
    report, _ = Report.objects.get_or_create(date=run.date, defaults={'article': article, 'run': run})
    if report.article_id != article.pk: raise SourceError('日报文章关联异常')
    if report.run.started_at > run.started_at: raise SourceError('较旧采集不能覆盖较新报告')
    for field, value in defaults.items(): setattr(article, field, value)
    article.published = auto_publish and not report.publication_hold
    if article.published and not article.published_at: article.published_at = run.finished_at
    article.save()
    countries = [Country.objects.get_or_create(name=name, defaults={'slug': slug})[0]
                 for name, slug in [('中国', 'china'), ('哈萨克斯坦', 'kazakhstan')]]
    article.countries.set(countries)
    article.related_resources.set(Article.objects.filter(kind='resources', published=True).filter(Q(slug='khorgos') | Q(title__icontains='霍尔果斯'))[:5])
    report.run = run
    report.save(update_fields=['run'])
    return report


def collect(*, scheduled=False, payload=None, now=None, finished_at=None):
    now = now or timezone.now()
    config, _ = Settings.objects.get_or_create(pk=1)
    token = str(uuid4())
    if not Settings.objects.filter(pk=1).filter(Q(lease_until__isnull=True) | Q(lease_until__lte=now)).update(lease_token=token, lease_until=now+timedelta(minutes=10)):
        return None
    run = None
    try:
        config.refresh_from_db()
        Run.objects.filter(status='running', started_at__lt=now-timedelta(minutes=10)).update(status='failed', finished_at=now, message='前次进程中断，已释放锁。')
        trigger, requested = due(config, now) if scheduled else ('manual', config.requested_at)
        if not trigger: return None
        run = Run.objects.create(date=now.astimezone(BEIJING).date(), started_at=now, trigger=trigger)
        if requested: Settings.objects.filter(pk=1, lease_token=token).update(handled_request_at=requested)
        supplied = payload is not None
        if not supplied: payload = fetch()
        finished = finished_at or (now if supplied else timezone.now())
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        run.raw_path = f'cgr/horgos/raw/{run.date:%Y/%m}/{digest(payload)}.json.gz'
        path = Path(django_settings.DATA_DIR)/run.raw_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists(): path.write_bytes(gzip.compress(raw))
        run.save(update_fields=['raw_path'])
        counts, details, skipped, limit_hit = normalize(payload, now, finished)
        with transaction.atomic():
            config.refresh_from_db()
            if config.lease_token != token or config.lease_until <= finished: raise SourceError('任务锁已失效，本轮不写入')
            summary, _ = Summary.objects.get_or_create(fingerprint=digest([run.date.isoformat(), counts]), defaults={
                'date': run.date, 'counts': counts, 'first_seen': now, 'last_seen': finished})
            Summary.objects.filter(pk=summary.pk, last_seen__lt=finished).update(last_seen=finished)
            versions = []
            for row in details:
                vehicle, created = Vehicle.objects.get_or_create(identity=row['identity'], defaults={**row, 'first_seen': now, 'last_seen': finished})
                if not created:
                    Vehicle.objects.filter(pk=vehicle.pk, last_seen__lte=finished).update(company=row['company'], status=row['status'], last_seen=finished)
                version, _ = VehicleVersion.objects.get_or_create(fingerprint=digest([row['identity'], row['company'], row['status']]), defaults={
                    'vehicle': vehicle, 'company': row['company'], 'status': row['status'], 'first_seen': now, 'last_seen': finished})
                VehicleVersion.objects.filter(pk=version.pk, last_seen__lt=finished).update(last_seen=finished)
                versions.append(version)
            run.records.set(versions)
            run.summary = summary
            run.row_count = len(versions)
            run.skipped_count = skipped
            run.limit_hit = limit_hit
            run.status = 'success'
            run.finished_at = finished
            run.message = f'当日明细 {len(versions)} 条；跳过非当日记录 {skipped} 条。源站汇总独立校验通过。'
            run.save()
            report = publish(run, config.auto_publish)
            run.message += ' 报告已发布。' if report.article.published else ' 报告保留为草稿或已撤回。'
            run.save(update_fields=['message'])
        return run
    except Exception as exc:
        if run:
            message = str(exc) if isinstance(exc, SourceError) else f'采集处理失败（{type(exc).__name__}），请检查服务日志。'
            if not isinstance(exc, SourceError): logger.exception('Horgos run %s failed', run.pk)
            Run.objects.filter(pk=run.pk).update(status='failed', finished_at=timezone.now(), message=message)
            run.refresh_from_db()
            return run
        raise
    finally:
        Settings.objects.filter(pk=1, lease_token=token).update(lease_token='', lease_until=None)
