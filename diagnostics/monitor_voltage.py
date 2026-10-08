"""Bounded recording of the identified voltage query on receiver firmware 8511."""
import argparse
import json
from pathlib import Path
import time
from query_version import query


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=int, default=120)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 300:
        parser.error('seconds must be 1..300')
    version = query()
    if version.get('firmware_version_hex') != '8511':
        raise RuntimeError('This diagnostic is restricted to the inspected receiver firmware 8511')
    deadline = time.monotonic() + args.seconds
    data = {'status': 'recording', 'started': time.time(), 'version': version,
            'samples': [], 'interpretation': 'voltage candidate, not battery percentage'}
    print('VOLTAGE_RECORDING_STARTED', flush=True)
    try:
        while time.monotonic() < deadline:
            sample = query('voltage_candidate')
            data['samples'].append(sample)
            args.out.write_text(json.dumps(data, indent=2), encoding='utf-8')
            print(json.dumps({'time': sample['time'], 'raw_value': sample.get('raw_value'),
                              'error': sample.get('error')}), flush=True)
            if sample['status'] != 'complete' or 'raw_value' not in sample:
                raise RuntimeError('Query failed or returned an unexpected report; stopping')
            time.sleep(min(2, max(0, deadline - time.monotonic())))
        data['status'] = 'complete'
    except Exception as error:
        data.update(status='error', error=str(error))
        raise
    finally:
        data['finished'] = time.time()
        args.out.write_text(json.dumps(data, indent=2), encoding='utf-8')
