"""Listen to the ZOWIE vendor input collection without sending output reports."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import time

from hid_probe import inventory, create, close, INVALID
from usb_capture import Overlapped, event, reset, read, wait, result, cancel
from device_lock import serialized_device


@serialized_device
def listen(seconds, out):
    devices = [d for d in inventory() if d.get('usage_page') == '0xff04'
               and d.get('lengths', {}).get('input')]
    if len(devices) != 1:
        raise RuntimeError(f'Expected one vendor input collection, found {len(devices)}')
    device = devices[0]
    handle = create(device['path'], 0x80000000, 3, None, 3, 0x40000000, None)
    if handle == INVALID:
        raise C.WinError(C.get_last_error())
    overlapped = Overlapped()
    overlapped.event = event(None, True, False, None)
    if not overlapped.event:
        close(handle)
        raise C.WinError(C.get_last_error())
    buffer = C.create_string_buffer(device['lengths']['input'])
    count = W.DWORD()
    pending = False
    data = {'status': 'listening', 'started': time.time(), 'seconds': seconds,
            'device': device, 'reports': []}

    def save():
        out.write_text(json.dumps(data, indent=2), encoding='utf-8')

    def record():
        data['reports'].append({'time': time.time(), 'hex': buffer.raw[:count.value].hex()})
        save()

    save()
    print('VENDOR_LISTENING_STARTED', flush=True)
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline:
            if not pending:
                reset(overlapped.event)
                if read(handle, buffer, len(buffer), C.byref(count), C.byref(overlapped)):
                    record()
                    continue
                error = C.get_last_error()
                if error != 997:
                    raise C.WinError(error)
                pending = True
            if wait(overlapped.event, 100) == 0:
                if not result(handle, C.byref(overlapped), C.byref(count), False):
                    raise C.WinError(C.get_last_error())
                pending = False
                record()
        data['status'] = 'complete'
    except Exception as error:
        data.update(status='error', error=str(error))
        raise
    finally:
        if pending:
            cancel(handle, C.byref(overlapped))
            if result(handle, C.byref(overlapped), C.byref(count), True):
                record()
        close(overlapped.event)
        close(handle)
        data['finished'] = time.time()
        save()
        print(json.dumps({'status': data['status'], 'reports': len(data['reports'])}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=int, default=90)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 300:
        parser.error('seconds must be 1..300')
    listen(args.seconds, args.out)
