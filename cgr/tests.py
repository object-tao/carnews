from datetime import date, datetime, timedelta, time
from html import escape
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import csv
import json
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, SimpleTestCase, override_settings
from django.utils import timezone
from openpyxl import load_workbook
from .catalog import CATALOG
from .exports import make_export
from .models import Checkpoint, CollectorSettings, CollectionRun, DailyReport, Observation
from .parser import MONTHS, SourceError, parse_calendar
from .service import BEIJING, collect, _due


def fixture(anchor, catalog=CATALOG, count=4):
    months = {v: k for k, v in MONTHS.items()}
    def short(day): return f'{day.day} {months[day.month]}'
    end = anchor + timedelta(days=count-1)
    html = f'<h4>Загруженность постов</h4><div>Актуально на: {anchor:%d.%m.%Y} 00:10</div><div>{short(anchor)}</div><div>{short(end)}</div>'
    for country, source, _, _ in catalog:
        html += f'<div class="row square-chart-row"><div class="square-chart-name"><span class="country-flag-{country}"></span>{escape(source)}</div><div>'
        for index in range(count):
            day = short(anchor+timedelta(days=index))
            if index == 1:
                level, text = 6, f'{day}<br><b>Выходной день</b>'
            elif index == 2:
                level, text = 0, f'{day}<br><b>Бронирование на эту дату ещё не открыто</b>'
            else:
                level, text = (1 if index == 0 else 3), f'Свободно на {day}<br><b>за 1 МРП: {0 if index == 0 else 12}<br>за 100 МРП: {0 if index == 0 else 2}</b>'
            html += f'<div class="square zag-level-{level}" title="{escape(text, quote=True)}"></div>'
        html += '</div></div>'
    return html + '<h4>Количество зарегистрированных водителей</h4>'


class ParserTests(SimpleTestCase):
    def test_new_year_holiday_and_not_open_are_preserved(self):
        start = date(2026, 12, 30)
        data = parse_calendar(fixture(start, count=8), start)
        self.assertEqual(len(data['rows']), 51)
        cells = data['rows'][0]['cells']
        self.assertEqual(cells[-1]['day'], date(2027, 1, 6))
        self.assertEqual(cells[1]['state'], 'holiday')
        self.assertEqual(cells[1]['quotas'], {})
        self.assertEqual(cells[2]['state'], 'not_open')
        self.assertEqual(cells[0]['quotas']['1'], 0)

    def test_source_day_can_be_previous_beijing_day(self):
        anchor = date(2026, 11, 8)
        self.assertEqual(parse_calendar(fixture(anchor), anchor+timedelta(days=1))['start'], anchor)

    def test_all_tiers_and_full_window_are_parsed(self):
        source = fixture(date(2026, 11, 9), count=61).replace('за 100 МРП:', 'за 25 МРП:')
        data = parse_calendar(source, date(2026, 11, 9))
        self.assertEqual(len(data['rows'][0]['cells']), 61)
        self.assertIn('25', data['rows'][0]['cells'][0]['quotas'])

    def test_malformed_missing_negative_duplicate_and_stale_fail_closed(self):
        anchor = date(2026, 11, 9)
        source = fixture(anchor)
        variants = [
            source.replace('за 1 МРП: 0', 'за 1 МРП: -5', 1),
            source.replace('за 1 МРП: 0', 'за 1 МРП: ?', 1),
            source.replace('за 1 МРП: 0', 'за 1 МРП: 1.5', 1),
            source.replace('за 1 МРП: 0', 'за 1 МРП: 1,000', 1),
            source.replace('zag-level-1', 'zag-level-9', 1),
            source.replace('Выходной день', 'Unknown status', 1),
            source.replace('Достык - Алашанькоу', 'Бахты - Покиту'),
            source.replace('Свободно на 9 ноя', 'Свободно на 10 ноя', 1),
            source.replace('Актуально на:', 'Missing update:'),
            source[:source.index('Количество зарегистрированных')],
        ]
        for html in variants:
            with self.subTest(html=html[:60]), self.assertRaises(SourceError):
                parse_calendar(html, anchor)
        with self.assertRaises(SourceError):
            parse_calendar(source, anchor+timedelta(days=3))


@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class CollectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_cgr', verbosity=0)

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.override = override_settings(DATA_DIR=Path(self.folder.name))
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.now = timezone.now()
        self.day = self.now.astimezone(BEIJING).date()
        self.html = fixture(self.day)

    def run_collection(self, **kwargs):
        return collect(html=self.html, now=self.now, **kwargs)

    def test_complete_publication_snapshot_and_same_day_idempotency(self):
        first = self.run_collection()
        self.assertEqual(first.status, 'success', first.message)
        self.assertEqual(first.observations.count(), 204)
        self.assertTrue((Path(self.folder.name)/first.raw_path).exists())
        report = DailyReport.objects.get()
        self.assertTrue(report.article.published)
        self.assertIn('首次有效采集', report.article.body)
        second = collect(html=self.html.replace('МРП: 12', 'МРП: 13'), now=self.now+timedelta(seconds=1))
        self.assertEqual(second.status, 'success', second.message)
        report.refresh_from_db()
        self.assertEqual(report.run_id, second.pk)
        self.assertEqual(DailyReport.objects.count(), 1)
        self.assertEqual(first.observations.count(), 204)
        report.article.refresh_from_db()
        self.assertIn('51 项名额发生变化', report.article.body)
        self.assertEqual(report.article.published_at, first.started_at)

    def test_partial_source_does_not_replace_previous_valid_report(self):
        first = self.run_collection()
        report = DailyReport.objects.get()
        before = report.article.body
        failed = collect(html=fixture(self.day, catalog=CATALOG[:-1]), now=self.now+timedelta(seconds=1))
        self.assertEqual(failed.status, 'failed')
        self.assertEqual(failed.observations.count(), 0)
        report.refresh_from_db()
        self.assertEqual(report.run_id, first.pk)
        self.assertEqual(report.article.body, before)

    def test_unknown_node_is_quarantined_and_country_changes_rejected(self):
        new = ('ru', 'New crossing', '新口岸', '')
        run = collect(html=fixture(self.day, catalog=CATALOG+[new]), now=self.now)
        self.assertEqual(run.status, 'failed')
        node = Checkpoint.objects.get(source_name='New crossing')
        self.assertTrue(node.needs_review)
        self.assertFalse(node.enabled)
        node.needs_review = False
        node.save()
        run = collect(html=self.html.replace('country-flag-cn', 'country-flag-ru', 1), now=self.now)
        self.assertEqual(run.status, 'failed')
        self.assertFalse(DailyReport.objects.exists())

    def test_publication_failure_rolls_back_observations_and_article(self):
        with patch('cgr.service.publish_report', side_effect=SourceError('模拟发布失败')):
            run = self.run_collection()
        self.assertEqual(run.status, 'failed')
        self.assertEqual(Observation.objects.count(), 0)
        self.assertEqual(DailyReport.objects.count(), 0)

    def test_manual_withdrawal_survives_rerun_and_draft_downloads_are_private(self):
        self.run_collection()
        report = DailyReport.objects.get()
        report.publication_hold = True
        report.save()
        report.article.published = False
        report.article.save()
        self.run_collection()
        report.refresh_from_db()
        self.assertFalse(report.article.published)
        self.assertEqual(self.client.get(report.get_absolute_url()).status_code, 404)
        self.assertNotContains(self.client.get('/sitemap.xml'), report.get_absolute_url())
        for fmt in ['csv', 'xlsx', 'html']:
            self.assertEqual(self.client.get(f'/border-reports/{report.pk}/export/{fmt}/').status_code, 404)
            self.assertEqual(self.client.get(f'/border-reports/{report.pk}/export/{fmt}/?preview=1').status_code, 404)
        user = get_user_model().objects.create_superuser('collector-admin', password='test-not-used-in-production')
        self.client.force_login(user)
        preview = self.client.get(f'/border-reports/{report.pk}/preview/?preview=1')
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(self.client.get(f'/border-reports/{report.pk}/export/csv/?preview=1').status_code, 200)

    def test_auto_publish_disabled_produces_a_draft(self):
        CollectorSettings.objects.update(auto_publish=False)
        self.run_collection()
        self.assertFalse(DailyReport.objects.get().article.published)

    def test_filters_exports_metadata_and_port_aliases(self):
        self.run_collection()
        report = DailyReport.objects.get()
        response = self.client.get('/news/border-updates/?country=ru')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['node_count'], 30)
        self.assertEqual(response.context['ports'].count(), 30)
        self.assertEqual(response.context['row_count'], 120)
        for alias, corrected in [('波基图', '巴克图'), ('杜拉特', '都拉塔')]:
            response = self.client.get('/news/border-updates/', {'q': alias})
            self.assertEqual(response.context['node_count'], 1)
            self.assertIn(corrected, response.context['groups'][0]['nodes'][0]['checkpoint'].name)
        self.assertEqual(self.client.get('/news/border-updates/?country=invalid').status_code, 400)
        self.assertEqual(self.client.get('/news/border-updates/?day=bad-date').status_code, 400)
        self.assertEqual(self.client.get('/news/border-updates/?port=1e100').status_code, 400)
        csv_response = self.client.get(f'/border-reports/{report.pk}/export/csv/?country=ru')
        rows = list(csv.reader(StringIO(csv_response.content.decode('utf-8-sig'))))
        self.assertEqual(len(rows), 181)  # 30 ports * (2 quoted days * 2 tiers + 2 non-quoted days).
        self.assertEqual({r[3] for r in rows[1:]}, {'俄罗斯'})
        self.assertTrue(any(r[9] == '0' for r in rows[1:]))
        self.assertTrue(any(r[9] == '' and r[7] == '源站标注休息日' for r in rows[1:]))
        response = self.client.get(report.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        schema = json.loads(response.content.decode().split('<script type="application/ld+json">')[1].split('</script>')[0])
        self.assertEqual(schema['articleSection'], '口岸动态')
        self.assertContains(self.client.get('/sitemap.xml'), report.get_absolute_url())
        self.assertContains(self.client.get('/news/'), '/news/border-updates/')

    def test_csv_xlsx_html_escape_text_and_preserve_numeric_zero_and_null(self):
        self.run_collection()
        report = DailyReport.objects.get()
        observations = list(report.run.observations.select_related('checkpoint')[:4])
        for obj in observations:
            obj.checkpoint.name = '=HYPERLINK("bad")'
            obj.checkpoint.source_name = '<script>alert(1)</script>'
        data, _ = make_export(report, observations, 'csv')
        self.assertIn("'=HYPERLINK", data.decode('utf-8-sig'))
        data, _ = make_export(report, observations, 'xlsx')
        book = load_workbook(BytesIO(data))
        sheet = book['预约明细']
        self.assertEqual(sheet['E2'].data_type, 's')
        self.assertEqual(sheet['J2'].value, 0)
        self.assertIsNone(sheet['J4'].value)
        data, _ = make_export(report, observations, 'html')
        self.assertNotIn('<script>alert', data.decode())
        self.assertIn('&lt;script&gt;', data.decode())

    def test_beijing_schedule_retry_limit_manual_queue_and_lease(self):
        config = CollectorSettings.objects.get()
        before = datetime(2026, 11, 10, 3, 9, tzinfo=BEIJING)
        due = before+timedelta(minutes=1)
        self.assertEqual(_due(config, before), (None, None))
        self.assertEqual(_due(config, due)[0], 'scheduled')
        for index in range(3):
            CollectionRun.objects.create(report_date=due.date(), started_at=due+timedelta(minutes=index*11),
                                         finished_at=due+timedelta(minutes=index*11), trigger='scheduled', status='failed')
        self.assertEqual(_due(config, due+timedelta(hours=1)), (None, None))
        config.enabled = False
        config.requested_at = due
        config.save()
        self.assertEqual(_due(config, due)[0], 'manual')
        CollectorSettings.objects.update(lease_token='other-worker', lease_until=self.now+timedelta(minutes=15))
        self.assertIsNone(self.run_collection())
        CollectorSettings.objects.update(lease_until=None)
        self.assertEqual(self.run_collection(scheduled=True).status, 'success')
        config.refresh_from_db()
        self.assertEqual(config.handled_request_at, config.requested_at)

    def test_admin_collect_action_is_authenticated_and_queued(self):
        url = '/admin/cgr/collectorsettings/'
        data = {'action': 'request_collection', '_selected_action': '1'}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertIsNone(CollectorSettings.objects.get().requested_at)
        user = get_user_model().objects.create_superuser('queue-admin', password='test-only-password')
        self.client.force_login(user)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertIsNotNone(CollectorSettings.objects.get().requested_at)

    def test_seed_does_not_reset_operator_names_or_enable_flags(self):
        node = Checkpoint.objects.first()
        node.name = '人工校订名称'
        node.enabled = False
        node.save()
        call_command('seed_cgr', verbosity=0)
        node.refresh_from_db()
        self.assertEqual(node.name, '人工校订名称')
        self.assertFalse(node.enabled)
