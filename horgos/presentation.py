"""Public report graphics use only the report's own validated aggregate snapshot."""
from django.http import Http404
from .client import CATEGORIES


def breakdown(items, total):
    subtotal = sum(value for _, value in items)
    consistent = subtotal == total
    show_shares = consistent and total > 0
    return {
        'total': f'{total:,}', 'subtotal': f'{subtotal:,}',
        'consistent': consistent, 'show_shares': show_shares, 'empty': total == 0 and consistent,
        'items': [{'label': label, 'value': f'{value:,}',
                   'share': f'{value / total * 100:.1f}' if show_shares else '',
                   'width': f'{value / total * 100:.3f}' if show_shares else '0'}
                  for label, value in items],
    }


def report_context(report):
    run = report.run
    if run.status != 'success' or not run.summary_id:
        raise Http404
    counts = run.summary.counts
    metrics = [
        ('commercialReleaseNum', '整车放行', 'release'),
        ('commercialNum', '整车预约', 'reservation'),
        ('heavyReleaseNum', '重车放行', 'release'),
        ('heavyNum', '重车预约', 'reservation'),
    ]
    vehicle_types = [('自驾', counts['commercialNumRelease']), ('笼车', counts['longCarNumRelease'])]
    cargo_types = sorted([(name, counts['categories'][name]) for name in CATEGORIES], key=lambda row: -row[1])
    return {
        'horgos_report': report, 'run': run,
        'metrics': [{'key': key, 'label': label, 'value': f'{counts[key]:,}', 'kind': kind} for key, label, kind in metrics],
        'vehicle_types': breakdown(vehicle_types, counts['commercialReleaseNum']),
        'cargo_types': breakdown(cargo_types, counts['heavyReleaseNum']),
    }
