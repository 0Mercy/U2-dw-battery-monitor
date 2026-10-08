"""Acceptance fixture only: never imports HID modules or talks to hardware."""
import json
from pathlib import Path
import sys
import time

fixture = json.loads((Path(__file__).resolve().parents[1]/'fixture.json').read_text(encoding='utf-8-sig'))
time.sleep(fixture.get('delay', 0))
if fixture.get('stderr_bytes'):
    sys.stderr.write('x' * fixture['stderr_bytes'])
if fixture.get('malformed'):
    print('not json')
else:
    print(json.dumps(fixture.get('response', {
        'status':'cached_voltage_only', 'estimated_percentage':85,
        'inferred_volts':4.04, 'snapshot_time':time.time()
    })))
sys.exit(fixture.get('exit_code', 0))
