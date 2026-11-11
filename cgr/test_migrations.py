from datetime import date
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class DeduplicationMigrationTests(TransactionTestCase):
    def test_existing_snapshots_survive_merge_and_reverse(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        old_target = [('cgr', '0001_initial')]
        try:
            executor.migrate(old_target)
            old = executor.loader.project_state(old_target).apps
            Run = old.get_model('cgr', 'CollectionRun')
            Port = old.get_model('cgr', 'Checkpoint')
            Cell = old.get_model('cgr', 'Observation')
            port = Port.objects.create(source_name='Migration test', name='测试', country='cn')
            runs = [Run.objects.create(report_date=date(2026,11,10), trigger='manual', status='success') for _ in range(2)]
            for index, run in enumerate(runs):
                Cell.objects.create(run=run, checkpoint=port, day=date(2026,11,10), state='full', level=1, quotas={'1':0})
                Cell.objects.create(run=run, checkpoint=port, day=date(2026,11,11), state='available', level=2, quotas={'1':index+1})
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            apps = executor.loader.project_state(latest).apps
            Run = apps.get_model('cgr', 'CollectionRun')
            Cell = apps.get_model('cgr', 'Observation')
            self.assertEqual(Cell.objects.count(), 3)
            for index, run in enumerate(runs):
                stored = Run.objects.get(pk=run.pk)
                self.assertEqual(stored.observations.count(), 2)
                self.assertEqual(stored.observations.get(day=date(2026,11,11)).quotas, {'1':index+1})
            executor = MigrationExecutor(connection)
            executor.migrate(old_target)
            old = executor.loader.project_state(old_target).apps
            self.assertEqual(old.get_model('cgr','Observation').objects.count(),4)
        finally:
            MigrationExecutor(connection).migrate(latest)
