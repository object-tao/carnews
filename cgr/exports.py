import csv
from io import BytesIO, StringIO
from django.template.loader import render_to_string
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from .catalog import SOURCE_URL
from .service import BEIJING

HEADERS = ['报告日期', '采集时间（北京时间）', '源站更新时间（未注明时区）', '哈方对接国家/地区',
           '口岸中文名', '源站俄文名称', '预约日期', '预约状态', 'МРП 档位', '剩余名额（个）', '源站色阶', '数据来源']


def export_rows(report, observations):
    for obj in observations:
        for tier, quota in (sorted(obj.quotas.items(), key=lambda pair: int(pair[0])) or [('', None)]):
            yield [str(report.date), report.run.started_at.astimezone(BEIJING).strftime('%Y-%m-%d %H:%M:%S'),
                   report.run.source_updated, obj.checkpoint.get_country_display(), obj.checkpoint.name,
                   obj.checkpoint.source_name, str(obj.day), obj.get_state_display(), int(tier) if tier else '',
                   quota, obj.level, SOURCE_URL]


def csv_safe(value):
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')):
        return "'" + value
    return value


def make_export(report, observations, format):
    rows = list(export_rows(report, observations))
    if format == 'csv':
        output = StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(HEADERS)
        writer.writerows([[csv_safe(v) for v in row] for row in rows])
        return output.getvalue().encode('utf-8-sig'), 'text/csv; charset=utf-8'
    if format == 'xlsx':
        workbook = Workbook()
        notes = workbook.active
        notes.title = '报告说明'
        notes.append(['报告', report.article.title])
        notes.append(['报告日期', str(report.date)])
        notes.append(['采集时间（北京时间）', report.run.started_at.astimezone(BEIJING).strftime('%Y-%m-%d %H:%M:%S')])
        notes.append(['源站更新时间', report.run.source_updated + '（源站未注明时区）'])
        notes.append(['筛选结果', f'{len({o.checkpoint_id for o in observations})} 个节点，{len(observations)} 条口岸日期记录'])
        notes.append(['预约日历', '本次采集时可见的预约安排，不是过去若干天的排队趋势。'])
        notes.append(['名额口径', '0 表示明确为零；休息日和尚未开放预约留空。МРП为源站档位标识，不是运费或吨位。'])
        notes.append(['适用范围', '可预约名额不等同于现场排队人数、拥堵程度或通关时长。'])
        notes.append(['来源', SOURCE_URL])
        notes.column_dimensions['A'].width = 26
        notes.column_dimensions['B'].width = 100
        sheet = workbook.create_sheet('预约明细')
        sheet.append(HEADERS)
        for row in rows:
            sheet.append(row)
        sheet.freeze_panes = 'G2'
        sheet.auto_filter.ref = sheet.dimensions
        for i, width in enumerate([15, 25, 28, 22, 38, 48, 16, 24, 14, 18, 12, 50], 1):
            sheet.column_dimensions[get_column_letter(i)].width = width
        for ws in workbook:
            for row in ws:
                for cell in row:
                    if isinstance(cell.value, str):
                        cell.data_type = 's'  # Keep source/admin text from becoming Excel formulas.
                    cell.alignment = Alignment(vertical='top', wrap_text=True)
            for cell in ws[1]:
                cell.font = Font(color='FFFFFF', bold=True)
                cell.fill = PatternFill('solid', fgColor='192C51')
        output = BytesIO()
        workbook.save(output)
        return output.getvalue(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    html = render_to_string('cgr/export.html', {'report': report, 'headers': HEADERS, 'rows': rows,
                                               'node_count': len({o.checkpoint_id for o in observations}), 'source_url': SOURCE_URL})
    return html.encode('utf-8'), 'text/html; charset=utf-8'
