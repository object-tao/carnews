import hashlib
import json
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


def reuse_cells(apps, schema_editor):
    Observation = apps.get_model('cgr', 'Observation')
    Run = apps.get_model('cgr', 'CollectionRun')
    through = Run.observations.through
    db = schema_editor.connection.alias
    times = dict(Run.objects.using(db).values_list('pk', 'started_at'))
    seen, links, duplicates, expected = {}, [], [], {}
    for obj in Observation.objects.using(db).order_by('pk').iterator():
        key = hashlib.sha256(json.dumps([obj.checkpoint_id, obj.day.isoformat(), obj.state, obj.level, obj.quotas], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        expected[obj.first_run_id] = expected.get(obj.first_run_id, 0) + 1
        if key in seen:
            master = seen[key]
            duplicates.append(obj.pk)
            Observation.objects.using(db).filter(pk=master, last_seen__lt=times[obj.first_run_id]).update(last_seen=times[obj.first_run_id])
        else:
            master = obj.pk
            seen[key] = master
            Observation.objects.using(db).filter(pk=master).update(fingerprint=key, last_seen=times[obj.first_run_id])
        links.append(through(collectionrun_id=obj.first_run_id, observation_id=master))
    through.objects.using(db).bulk_create(links, batch_size=100)
    Observation.objects.using(db).filter(pk__in=duplicates).delete()
    for run_id, count in expected.items():
        if through.objects.using(db).filter(collectionrun_id=run_id).count() != count:
            raise RuntimeError('CGR snapshot membership changed during migration')


def restore_cells(apps, schema_editor):
    Observation = apps.get_model('cgr', 'Observation')
    Run = apps.get_model('cgr', 'CollectionRun')
    db = schema_editor.connection.alias
    for run in Run.objects.using(db).all():
        for obj in run.observations.using(db).all():
            if obj.first_run_id != run.pk:
                Observation.objects.using(db).create(first_run_id=run.pk, checkpoint_id=obj.checkpoint_id,
                    day=obj.day, state=obj.state, level=obj.level, quotas=obj.quotas,
                    fingerprint=obj.fingerprint, last_seen=obj.last_seen)


class Migration(migrations.Migration):
    dependencies = [('cgr', '0001_initial')]
    operations = [
        migrations.RemoveConstraint('observation', 'cgr_unique_observation'),
        migrations.RenameField('observation', 'run', 'first_run'),
        migrations.AlterField('observation', 'first_run', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='first_observations', to='cgr.collectionrun')),
        migrations.AddField('observation', 'fingerprint', models.CharField(max_length=64, null=True, editable=False)),
        migrations.AddField('observation', 'last_seen', models.DateTimeField(null=True, verbose_name='最近采集确认')),
        migrations.AddField('collectionrun', 'observations', models.ManyToManyField(blank=True, related_name='runs', to='cgr.observation')),
        migrations.RunPython(reuse_cells, restore_cells),
        migrations.AlterField('observation', 'fingerprint', models.CharField(max_length=64, unique=True, editable=False)),
        migrations.AlterField('observation', 'last_seen', models.DateTimeField(default=django.utils.timezone.now, verbose_name='最近采集确认')),
    ]
