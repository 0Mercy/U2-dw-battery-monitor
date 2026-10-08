"""One bounded tray reading; stdout contains a compact JSON result only."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'diagnostics'))
from battery_percentage import interpret_snapshot, load_calibration, read_live_snapshot
from battery_percentage import UnsupportedReceiverError
from device_lock import DeviceBusyError
from query_version import DeviceUnavailableError


def read_battery():
    try:
        calibration = load_calibration(ROOT / 'diagnostics/full-battery-calibration.json')
    except (OSError, ValueError, KeyError, TypeError):
        return {'status': 'calibration_error', 'estimated_percentage': None}
    try:
        return interpret_snapshot(read_live_snapshot(), calibration)
    except DeviceBusyError:
        status = 'device_busy'
    except DeviceUnavailableError:
        status = 'receiver_missing'
    except UnsupportedReceiverError:
        status = 'unsupported_receiver'
    except Exception:
        # Avoid leaking device instance paths into the tray's status file.
        status = 'read_error'
    return {'status': status, 'estimated_percentage': None}


if __name__ == '__main__':
    print(json.dumps(read_battery(), ensure_ascii=True))
