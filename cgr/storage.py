import hashlib
import json
from .models import Observation


def observation_hash(checkpoint_id, day, state, level, quotas):
    return hashlib.sha256(json.dumps([checkpoint_id, day.isoformat(), state, level, quotas],
                                    sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def attach_observations(run, observations):
    """Reuse unchanged immutable cells; each run retains its exact membership."""
    rows = {}
    for obj in observations:
        key = observation_hash(obj.checkpoint_id, obj.day, obj.state, obj.level, obj.quotas)
        obj.fingerprint = key
        obj.last_seen = run.started_at
        rows[key] = obj
    existing = {obj.fingerprint: obj for obj in Observation.objects.filter(fingerprint__in=rows)}
    Observation.objects.bulk_create([obj for key, obj in rows.items() if key not in existing], batch_size=100)
    stored = list(Observation.objects.filter(fingerprint__in=rows))
    Observation.objects.filter(pk__in=[o.pk for o in stored], last_seen__lt=run.started_at).update(last_seen=run.started_at)
    run.observations.set(stored)
