"""Strict parsing of the public reservation calendar, independent of Django."""
from datetime import datetime, timedelta
from html import unescape
from html.parser import HTMLParser
import re


class SourceError(ValueError):
    pass


MONTHS = dict(zip('янв фев мар апр май июн июл авг сен окт ноя дек'.split(), range(1, 13)))
DATE_PATTERN = r'(\d{1,2})\s+(' + '|'.join(MONTHS) + r')\b'


class CalendarHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.depth = 0
        self.name_depth = None
        self.row_depth = None
        self.prefix = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get('class', '').split()
        if tag == 'div':
            self.depth += 1
        if 'square-chart-row' in classes:
            if self.row is not None:
                raise SourceError('源站口岸行结构异常')
            self.row = {'name': '', 'country': '', 'cells': []}
            self.row_depth = self.depth
        if self.row is not None:
            if 'square-chart-name' in classes:
                self.name_depth = self.depth
            flags = [c.removeprefix('country-flag-') for c in classes if c.startswith('country-flag-')]
            if flags:
                self.row['country'] = flags[0]
            if 'square' in classes:
                levels = [c.removeprefix('zag-level-') for c in classes if c.startswith('zag-level-')]
                if len(levels) != 1 or not levels[0].isdigit() or 'title' not in attrs:
                    raise SourceError('源站预约单元格缺少等级或说明')
                self.row['cells'].append((int(levels[0]), attrs['title']))

    def handle_data(self, data):
        if self.row is not None and self.name_depth is not None:
            self.row['name'] += data
        elif not self.rows and self.row is None:
            self.prefix.append(data)

    def handle_endtag(self, tag):
        if tag == 'div':
            if self.name_depth == self.depth:
                self.name_depth = None
            if self.row is not None and self.row_depth == self.depth:
                self.row['name'] = ' '.join(self.row['name'].split())
                self.rows.append(self.row)
                self.row = None
                self.row_depth = None
            self.depth -= 1


def calendar_date(text, anchor):
    match = re.search(DATE_PATTERN, text.lower())
    if not match:
        raise SourceError('无法识别预约日期')
    day, month = int(match[1]), MONTHS[match[2]]
    dates = []
    for year in (anchor.year - 1, anchor.year, anchor.year + 1):
        try:
            dates.append(anchor.replace(year=year, month=month, day=day))
        except ValueError:
            pass
    if not dates:
        raise SourceError('预约日期无效')
    return min(dates, key=lambda value: abs((value - anchor).days))


def parse_calendar(html, captured_date):
    if 'Загруженность постов' not in html or 'Количество зарегистрированных' not in html:
        raise SourceError('未找到完整口岸预约区块')
    section = html.split('Загруженность постов', 1)[1].split('Количество зарегистрированных', 1)[0]
    parser = CalendarHTML()
    parser.feed(section)
    if parser.row is not None or not parser.rows:
        raise SourceError('口岸预约区块为空或被截断')
    prefix = ' '.join(parser.prefix)
    update = re.search(r'Актуально на:\s*(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})', prefix)
    if not update:
        raise SourceError('源站未提供预约区块更新时间')
    source_updated = datetime.strptime(update[1], '%d.%m.%Y %H:%M')
    anchor = source_updated.date()
    if not -1 <= (captured_date - anchor).days <= 1:
        raise SourceError('源站预约区块日期过旧或晚于采集日期，暂停发布')
    bounds = re.findall(DATE_PATTERN, prefix.lower())
    if len(bounds) != 2:
        raise SourceError('无法确认源站预约日历起止范围')
    start, end = [calendar_date(' '.join(item), anchor) for item in bounds]
    if end < start:
        end = end.replace(year=end.year + 1)
    count = (end - start).days + 1
    if not 1 <= count <= 120 or abs((start - anchor).days) > 1:
        raise SourceError('源站预约日历范围异常')
    names = set()
    for row in parser.rows:
        if not row['name'] or row['name'] in names or not row['country']:
            raise SourceError('口岸名称重复、为空或缺少国家标识')
        names.add(row['name'])
        if len(row['cells']) != count:
            raise SourceError(f"{row['name']}：预约日历不完整")
        cells = []
        tiers = set()
        for index, (level, tooltip) in enumerate(row['cells']):
            text = re.sub('<[^>]*>', ' ', unescape(tooltip))
            day = calendar_date(text, start + timedelta(days=index))
            if day != start + timedelta(days=index):
                raise SourceError(f"{row['name']}：预约日期缺失、重复或乱序")
            fees = re.findall(r'за\s+(\d+)\s+МРП\s*:\s*(\d(?:[\d\s\u00a0]*\d)?)(?=\s*(?:за\s+\d+\s+МРП|$))', text)
            quotas = {str(int(k)): int(re.sub(r'\s', '', v)) for k, v in fees}
            if len(quotas) != len(fees) or any(int(k) <= 0 or v > 1000000 for k, v in quotas.items()):
                raise SourceError('源站预约档位或名额异常')
            if 'Выходной день' in text and level == 6 and not quotas:
                state = 'holiday'
            elif 'Бронирование на эту дату ещё не открыто' in text and level == 0 and not quotas:
                state = 'not_open'
            elif 'Свободно на' in text and 1 <= level <= 5 and quotas:
                # Fail closed on unparsed/negative/partial fee values.
                if text.count('МРП') != len(quotas):
                    raise SourceError('预约名额含无法识别的值')
                state = 'available' if any(quotas.values()) else 'full'
                tiers.add(tuple(sorted(quotas, key=int)))
            else:
                raise SourceError(f"{row['name']}：无法识别预约状态（色阶 {level}）")
            cells.append({'day': day, 'level': level, 'state': state, 'quotas': quotas})
        if len(tiers) > 1:
            raise SourceError(f"{row['name']}：部分日期缺少预约档位")
        row['cells'] = cells
    return {'source_updated': update[1], 'start': start, 'end': end, 'rows': parser.rows}
