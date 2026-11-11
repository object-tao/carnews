from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, SimpleTestCase, override_settings
from django.utils import timezone
from .client import BEIJING, CATEGORIES, SourceError, normalize
from .models import Settings, Run, Summary, Vehicle, VehicleVersion, Report
from .service import collect, due


def fixture(now):
    current = now.astimezone(BEIJING)
    row = {'reservation': 'PRIVATE-RESERVATION-123', 'org': 'PRIVATE-COMPANY-XYZ', 'status': '已放行', 'time': current.strftime('%Y-%m-%d %H:%M')}
    old = {**row, 'reservation': 'YESTERDAY-ROW', 'time': (current-timedelta(days=1)).strftime('%Y-%m-%d %H:%M')}
    return {'commercial': {'flag': 1, 'info': [row, row.copy(), old]}, 'heavy': {'flag': 1, 'info': [{**row, 'reservation': 'HEAVY-456'}]},
            'totals': {'commercialNum': 10, 'commercialReleaseNum': 8, 'heavyNum': 20, 'heavyReleaseNum': 18},
            'car_types': {'commercialNumRelease': 5, 'longCarNumRelease': 3},
            'categories': {'info': [{'type': key, 'num': i} for i, key in enumerate(CATEGORIES)]}}


@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class HorgosTests(TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        context = override_settings(DATA_DIR=Path(folder.name))
        context.enable()
        self.addCleanup(context.disable)
        self.now = (timezone.now()-timedelta(days=1)).astimezone(BEIJING).replace(hour=10, minute=0, second=0, microsecond=0)
        self.payload = fixture(self.now)

    def collect(self, **kwargs): return collect(payload=self.payload, now=self.now, **kwargs)

    def test_same_round_current_day_dedup_and_private_details(self):
        first = self.collect()
        self.assertEqual(first.status, 'success', first.message)
        self.assertEqual((first.row_count, first.skipped_count), (2, 1))
        self.assertEqual(Vehicle.objects.count(), 2)
        self.assertFalse(Vehicle.objects.filter(number='YESTERDAY-ROW').exists())
        second = collect(payload=self.payload, now=self.now+timedelta(minutes=2))
        self.assertEqual(second.status, 'success', second.message)
        self.assertEqual(Vehicle.objects.count(), 2)
        self.assertEqual(VehicleVersion.objects.count(), 2)
        self.assertEqual(Summary.objects.count(), 1)
        self.assertEqual(Report.objects.count(), 1)
        self.assertEqual(first.records.count(), 2)
        self.assertEqual(second.records.count(), 2)
        self.assertEqual(Vehicle.objects.first().last_seen, second.finished_at)
        article = Report.objects.get().article
        self.assertIn('| 整车预约 | 10 |', article.body)
        self.assertIn('10:02:00', article.body)
        rendered = self.client.get(article.get_absolute_url())
        self.assertContains(rendered, '<dt>整车预约</dt>', html=True)
        self.assertContains(rendered, '<dt>跨境电商（清单模式）</dt>', html=True)
        self.assertContains(rendered, 'horgos-metric-release')
        for url in [article.get_absolute_url(), article.get_absolute_url()+'?preview=1&format=csv&details=1', '/news/border-updates/', '/sitemap.xml']:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, 'PRIVATE-COMPANY-XYZ')
            self.assertNotContains(response, 'PRIVATE-RESERVATION-123')
            self.assertNotContains(response, 'cgr-detail-table')
            self.assertNotContains(response, '/export/')
        self.assertContains(self.client.get('/sitemap.xml'), article.get_absolute_url())
        self.assertNotContains(self.client.get(article.get_absolute_url()), 'YESTERDAY-ROW')
        self.assertEqual(self.client.get('/admin/horgos/vehicle/').status_code, 302)

    def test_changed_record_updates_entity_and_preserves_batch_version(self):
        first = self.collect()
        changed = deepcopy(self.payload)
        for row in changed['commercial']['info'][:2]: row['status'] = '已完成'
        second = collect(payload=changed, now=self.now+timedelta(minutes=3))
        self.assertEqual(second.status, 'success', second.message)
        self.assertEqual(Vehicle.objects.count(), 2)
        self.assertEqual(VehicleVersion.objects.count(), 3)
        self.assertEqual(first.records.get(vehicle__kind='commercial').status, '已放行')
        self.assertEqual(second.records.get(vehicle__kind='commercial').status, '已完成')
        self.assertEqual(Vehicle.objects.get(kind='commercial').status, '已完成')

    def test_failure_never_uses_previous_summary_or_publishes_zero(self):
        valid = self.collect()
        report = Report.objects.get()
        before = report.article.body
        malformed = deepcopy(self.payload)
        del malformed['totals']['heavyNum']
        failed = collect(payload=malformed, now=self.now+timedelta(minutes=1))
        self.assertEqual(failed.status, 'failed')
        self.assertEqual(failed.records.count(), 0)
        report.refresh_from_db()
        self.assertEqual(report.run_id, valid.pk)
        self.assertEqual(report.article.body, before)
        with patch('horgos.service.fetch', side_effect=SourceError('源站失败')):
            failed = collect(now=self.now+timedelta(minutes=2))
        self.assertEqual(failed.status, 'failed')
        self.assertEqual(Summary.objects.count(), 1)

    def test_normalization_rejects_missing_categories_conflicts_and_bad_counts(self):
        variants = []
        for value in [None, True, -1, 1.2, 'bad']:
            data = deepcopy(self.payload); data['totals']['heavyNum'] = value; variants.append(data)
        data = deepcopy(self.payload); data['categories']['info'].pop(); variants.append(data)
        data = deepcopy(self.payload); data['commercial']['info'][1]['org'] = 'conflicting'; variants.append(data)
        data = deepcopy(self.payload); data['heavy']['info'][0]['time'] = '2026-11-11'; variants.append(data)
        data = deepcopy(self.payload); data['heavy'] = {'flag': 0, 'info': []}; variants.append(data)
        data = deepcopy(self.payload); del data['commercial']['flag']; variants.append(data)
        for data in variants:
            with self.subTest(data=data), self.assertRaises(SourceError): normalize(data, self.now, self.now)
        data = deepcopy(self.payload); data['totals']['heavyNum'] = 0
        self.assertEqual(normalize(data, self.now, self.now)[0]['heavyNum'], 0)

    def test_midnight_and_slow_batches_are_rejected(self):
        midnight = self.now.replace(hour=23, minute=59)
        for finished in [midnight+timedelta(minutes=2), self.now+timedelta(minutes=6)]:
            started = midnight if finished.date()!=self.now.date() else self.now
            run = collect(payload=fixture(started), now=started, finished_at=finished)
            self.assertEqual(run.status, 'failed')
        self.assertFalse(Report.objects.exists())

    def test_same_values_different_day_are_not_merged(self):
        self.collect()
        tomorrow = self.now+timedelta(days=1)
        run = collect(payload=fixture(tomorrow), now=tomorrow)
        self.assertEqual(run.status, 'success', run.message)
        self.assertEqual(Report.objects.count(), 2)
        self.assertEqual(Summary.objects.count(), 2)
        self.assertEqual(Vehicle.objects.count(), 4)

    def test_publication_rollback_and_manual_hold(self):
        with patch('horgos.service.publish', side_effect=SourceError('发布失败')):
            self.assertEqual(self.collect().status, 'failed')
        self.assertEqual(Vehicle.objects.count(), 0)
        self.assertEqual(Summary.objects.count(), 0)
        self.collect()
        report = Report.objects.get(); report.publication_hold=True; report.save()
        report.article.published=False; report.article.save()
        self.collect()
        report.refresh_from_db()
        self.assertFalse(report.article.published)
        self.assertEqual(self.client.get(report.article.get_absolute_url()).status_code, 404)

    def test_schedule_2350_retry_manual_and_lease(self):
        config = Settings.objects.create()
        before = self.now.replace(hour=23, minute=49)
        self.assertEqual(due(config, before)[0], None)
        at = before+timedelta(minutes=1)
        self.assertEqual(due(config, at)[0], 'scheduled')
        self.assertEqual(due(config, at+timedelta(minutes=10))[0], None)
        Settings.objects.update(lease_token='other', lease_until=self.now+timedelta(minutes=10))
        self.assertIsNone(self.collect())
        Settings.objects.update(lease_until=None)
        config.requested_at = self.now; config.enabled=False; config.save()
        run = self.collect(scheduled=True)
        self.assertEqual(run.trigger, 'manual')
        self.assertEqual(run.status, 'success', run.message)

    def test_admin_can_query_versions_and_unified_report_index(self):
        self.collect()
        user=get_user_model().objects.create_superuser('horgos-admin', password='test-only')
        self.client.force_login(user)
        for url in ['/admin/horgos/vehicle/', '/admin/horgos/vehicleversion/', '/admin/horgos/run/', '/admin/horgos/summary/']:
            self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.get('/admin/horgos/vehicle/?q=PRIVATE-COMPANY-XYZ')
        self.assertContains(response, 'PRIVATE-RESERVATION-123')
        response = self.client.get(f'/admin/horgos/vehicleversion/?runs__id__exact={Run.objects.get().pk}')
        self.assertContains(response, 'PRIVATE-RESERVATION-123')
        response = self.client.get('/news/border-updates/?source=horgos&country=cn')
        self.assertContains(response, Report.objects.get().article.title)
        self.assertNotContains(self.client.get('/news/border-updates/?source=cgr'), Report.objects.get().article.title)


class BreakdownTests(SimpleTestCase):
    def test_shares_only_when_parts_match_the_same_group_total(self):
        from .presentation import breakdown
        matched = breakdown([('自驾', 164), ('笼车', 566)], 730)
        self.assertTrue(matched['show_shares'])
        self.assertEqual([row['share'] for row in matched['items']], ['22.5', '77.5'])
        mismatch = breakdown([('自驾', 164), ('笼车', 566)], 731)
        self.assertFalse(mismatch['consistent'])
        self.assertFalse(mismatch['show_shares'])
        self.assertTrue(all(row['share'] == '' for row in mismatch['items']))

    def test_zero_group_keeps_real_zero_values_without_inventing_shares(self):
        from .presentation import breakdown
        result = breakdown([('自驾', 0), ('笼车', 0)], 0)
        self.assertTrue(result['empty'])
        self.assertFalse(result['show_shares'])
        self.assertEqual([row['value'] for row in result['items']], ['0', '0'])
