"""Application-owned release preparation, executed after the server backup."""
import os
from pathlib import Path
import sys

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.core.management import call_command
from django.conf import settings

call_command('check',deploy=True,fail_level='WARNING')
call_command('migrate',interactive=False)
call_command('seed_content')
call_command('import_ports',publish_reviewed=True)
call_command('publish_reviewed_ports')
call_command('backfill_port_images')
call_command('upgrade_port_images')
call_command('import_knowledge',publish=True)
call_command('import_vehicles',publish=True)
bridge_originals=settings.DATA_DIR/'private-imports/bridge-source-20261108'
call_command('import_bridges',publish=True,original_dir=bridge_originals if bridge_originals.is_dir() else None)
call_command('collectstatic',interactive=False)
