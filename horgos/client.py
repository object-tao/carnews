"""Adapted from the user's Desktop/11/holgos_client.py field mappings.

Strict TLS, same-round fetches and explicit failure replace silent zero defaults.
The source has no record ID; (type, reservation, business timestamp) identifies
a business event. A status/company correction creates a version, not a new event.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.request import Request, urlopen
from urllib.error import URLError
import hashlib
import json
import time

BEIJING = ZoneInfo('Asia/Shanghai')
SOURCE_URL = 'https://horgosgnss.horgoseport.com/horgos/api'
HEADERS = {'User-Agent': '5/WIFI MiniProgramEnv/Mac MacWechat/WMPF MacWechat/3.8.9(0x13080911) XWEB/1111',
           'Referer': 'https://servicewechat.com/wx6a7f63e8d9d31741/70/page-frame.html', 'xweb_xhr': '1', 'Cache-Control': 'no-cache'}
CATEGORIES = ['百货', '设备', '果蔬', '跨境电商', '跨境电商（清单模式）', '笼车']
FIELDS = {'commercialNum': '整车预约', 'commercialReleaseNum': '整车放行', 'heavyNum': '重车预约', 'heavyReleaseNum': '重车放行',
          'commercialNumRelease': '自驾放行', 'longCarNumRelease': '笼车放行'}
ENDPOINTS = {'commercial': 'getInfoList?type=1&status=0', 'heavy': 'getInfoList?type=0&status=0',
             'totals': 'postNumNow', 'car_types': 'postNumByCarType', 'categories': 'postNumByType'}


class SourceError(ValueError): pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def request_json(endpoint):
    for attempt in range(3):
        try:
            method = 'GET' if endpoint.startswith('get') else 'POST'
            req = Request(f'{SOURCE_URL}/{endpoint}', headers=HEADERS, method=method, data=None if method == 'GET' else b'')
            with urlopen(req, timeout=20) as response:
                if not response.url.startswith(SOURCE_URL + '/'):
                    raise SourceError('源接口出现未配置跳转')
                if int(response.headers.get('Age', '0')) > 0:
                    raise SourceError('源接口返回缓存响应，暂停发布')
                raw = response.read(4*1024*1024+1)
            if len(raw) > 4*1024*1024: raise SourceError('接口响应超过限制')
            data = json.loads(raw)
            if not isinstance(data, dict): raise SourceError('接口响应结构不正确')
            return data
        except (URLError, TimeoutError, OSError):
            if attempt == 2: raise SourceError(f'接口连接失败：{endpoint.split("?")[0]}，已重试三次') from None
            time.sleep(1 + attempt)


def fetch():
    # A new mapping every invocation: never fill failures from earlier batches.
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {key: pool.submit(request_json, endpoint) for key, endpoint in ENDPOINTS.items()}
        return {key: future.result() for key, future in futures.items()}


def count(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).isascii() or not str(value).isdigit():
        raise SourceError('统计字段缺失或不是非负整数')
    result = int(value)
    if result > 100000000: raise SourceError('统计字段超出合理范围')
    return result


def normalize(payload, started_at, finished_at):
    day = started_at.astimezone(BEIJING).date()
    if finished_at.astimezone(BEIJING).date() != day:
        raise SourceError('本轮采集跨越北京时间零点，不作为前一日数据发布')
    if finished_at < started_at or finished_at-started_at > timedelta(minutes=5):
        raise SourceError('采集用时异常，暂停发布')
    totals, cars, categories = payload['totals'], payload['car_types'], payload['categories']
    summary = {key: count(totals.get(key)) for key in list(FIELDS)[:4]}
    summary.update({key: count(cars.get(key)) for key in list(FIELDS)[4:]})
    rows = categories.get('info')
    if not isinstance(rows, list): raise SourceError('货类统计缺失')
    groups = {}
    for item in rows:
        name = item.get('type')
        if name not in CATEGORIES or name in groups: raise SourceError('货类名称未知或重复，需核对')
        groups[name] = count(item.get('num'))
    if set(groups) != set(CATEGORIES): raise SourceError('货类统计不完整')
    summary['categories'] = groups
    details, skipped, limit_hit = {}, 0, False
    for kind in ['commercial', 'heavy']:
        if payload[kind].get('flag') not in (1, '1'):
            raise SourceError('车辆明细接口未返回成功标记，暂停发布')
        rows = payload[kind].get('info')
        if not isinstance(rows, list) or len(rows) > 1000: raise SourceError('车辆明细结构异常')
        limit_hit |= len(rows) == 1000
        for row in rows:
            number, company, status = row.get('reservation'), row.get('org'), row.get('status')
            stamp = str(row.get('time', '')).strip()
            try:
                if len(stamp) not in (16, 19): raise ValueError('Expected source timestamp')
                occurred = datetime.fromisoformat(stamp)
                occurred = occurred.replace(tzinfo=BEIJING) if occurred.tzinfo is None else occurred.astimezone(BEIJING)
            except ValueError:
                raise SourceError('明细业务时间无法解析，暂停发布') from None
            if occurred > finished_at + timedelta(minutes=5): raise SourceError('明细业务时间晚于采集时间')
            if occurred.date() != day:
                skipped += 1
                continue
            if not isinstance(number, str) or not number.strip() or len(number) > 100: raise SourceError('业务编号缺失或异常')
            if not isinstance(company, str) or len(company) > 200 or not isinstance(status, str) or not status.strip() or len(status) > 80:
                raise SourceError('企业或状态字段异常')
            number, company, status = number.strip(), company.strip(), status.strip()
            identity = digest(['horgos', kind, number, occurred.isoformat()])
            item = dict(identity=identity, kind=kind, number=number, occurred_at=occurred, company=company, status=status)
            if identity in details and details[identity] != item: raise SourceError('本轮同一业务编号存在冲突记录')
            details[identity] = item
    return summary, list(details.values()), skipped, limit_hit
