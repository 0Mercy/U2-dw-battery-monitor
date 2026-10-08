"""Summarize recorded observations without querying or changing the device."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
run = Path(sys.argv[1])
rows = []
for line in (run/'tray-observations.jsonl').read_text(encoding='utf-8-sig').splitlines():
    try:
        rows.append(json.loads(line))
    except json.JSONDecodeError:
        pass  # A live observer may not have finished its last line yet.


def timestamp(value):
    return datetime.fromisoformat(value).timestamp()


transitions = []
gaps = []
sessions = {}
previous = None
for row in rows:
    state = row.get('state') or {}
    signature = (state.get('pid'), state.get('status'))
    if previous is None or signature != previous:
        transitions.append({'observed_at':row['observed_at'],'pid':state.get('pid'),
                            'status':state.get('status'),'label':state.get('label')})
        previous = signature
    process = row.get('process')
    if process:
        sessions.setdefault(str(process['id']), []).append(row)
for left, right in zip(rows, rows[1:]):
    seconds = timestamp(right['observed_at']) - timestamp(left['observed_at'])
    if seconds > 10:
        gaps.append({'from':left['observed_at'],'to':right['observed_at'],'seconds':seconds,
                     'first_after_gap':right.get('state')})

resources = {}
for pid, samples in sessions.items():
    start, finish = samples[0], samples[-1]
    duration = timestamp(finish['observed_at']) - timestamp(start['observed_at'])
    cpu = finish['process']['cpu_seconds'] - start['process']['cpu_seconds']
    resources[pid] = {
        'observed_seconds':duration, 'cpu_seconds_delta':cpu,
        'mean_one_core_cpu_percent':100*cpu/duration if duration else None,
        'private_bytes_min':min(r['process']['private_bytes'] for r in samples),
        'private_bytes_max':max(r['process']['private_bytes'] for r in samples),
        'handles_min':min(r['process']['handles'] for r in samples),
        'handles_max':max(r['process']['handles'] for r in samples),
        'first':start['observed_at'],'last':finish['observed_at'],
    }

source_paths = ['tray/TrayApp.cs','tray/start.ps1','tray/read_battery.py','Start-U2DW.vbs',
                'diagnostics/battery_percentage.py','diagnostics/query_version.py','diagnostics/device_lock.py',
                'tests/test_battery.py','tests/TrayAcceptance.cs','tests/run-tray-components.ps1']
evidence = json.loads((ROOT/'diagnostics/full-battery-calibration-evidence.json').read_text(encoding='utf-8'))
digest = hashlib.sha256((ROOT/'diagnostics'/evidence['record_file']).read_bytes()).hexdigest()
summary = {'created_at':datetime.now().astimezone().isoformat(), 'observation_count':len(rows),
           'transitions':transitions,'observation_gaps':gaps,'resources':resources,
           'calibration_record_hash_matches':digest == evidence['record_sha256'],
           'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in source_paths},
           'limitations':['Recorded times are observations, not exact physical action times.',
                          'A gap alone does not prove Windows slept; correlate with user confirmation and power events.',
                          'A bounded session is not a multi-day reliability or capacity-accuracy test.']}
(run/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in summary.items() if k != 'source_sha256'},ensure_ascii=False,indent=2))
