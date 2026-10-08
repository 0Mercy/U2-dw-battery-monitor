"""Send only identified read-only queries: versions and cached voltage.

This does not accept arbitrary commands and does not enter firmware update mode.
"""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import time
from hid_probe import inventory, create, close, INVALID, api, K, P
from usb_capture import Overlapped, event, read, wait, result, cancel
from device_lock import serialized_device

write = api(K, 'WriteFile', W.BOOL, [P, P, W.DWORD, P, P])


class DeviceUnavailableError(RuntimeError):
    pass


@serialized_device
def query(kind='firmware_version'):
    commands = {'firmware_version': '08 b4 40', 'voltage_candidate': '08 b4 15',
                'mouse_firmware_version': '08 b4 25'}
    if kind not in commands:
        raise ValueError('Only identified read-only queries are allowed')
    devices = inventory()
    inputs = [d for d in devices if d.get('usage_page') == '0xff04']
    outputs = [d for d in devices if d.get('usage_page') == '0xff03']
    if not inputs and not outputs:
        raise DeviceUnavailableError('Receiver not found')
    if len(inputs) != 1 or len(outputs) != 1:
        raise RuntimeError('Expected exactly one matching input/output collection pair')
    if inputs[0]['lengths']['input'] != 16 or outputs[0]['lengths']['output'] != 16:
        raise RuntimeError('Unexpected report lengths')
    handles = []
    pending = []
    events = []
    response = {'time': time.time(), 'purpose': kind,
                'input_path': inputs[0]['path'], 'output_path': outputs[0]['path']}
    try:
        for device, access in [(inputs[0], 0x80000000), (outputs[0], 0x40000000)]:
            handle = create(device['path'], access, 3, None, 3, 0x40000000, None)
            if handle == INVALID:
                raise C.WinError(C.get_last_error())
            handles.append(handle)
        read_buffer = C.create_string_buffer(16)
        write_buffer = C.create_string_buffer(bytes.fromhex(commands[kind]) + bytes(13), 16)
        response['request_hex'] = write_buffer.raw.hex()
        operations = []
        for handle, function, buffer in [(handles[0], read, read_buffer), (handles[1], write, write_buffer)]:
            overlapped = Overlapped()
            overlapped.event = event(None, True, False, None)
            if not overlapped.event:
                raise C.WinError(C.get_last_error())
            events.append(overlapped.event)
            count = W.DWORD()
            complete = function(handle, buffer, len(buffer), C.byref(count), C.byref(overlapped))
            if not complete:
                error = C.get_last_error()
                if error != 997:
                    raise C.WinError(error)
                pending.append((handle, overlapped, buffer))
            operations.append((handle, overlapped, buffer, count, bool(complete)))
        for index in (1, 0):
            handle, overlapped, buffer, count, complete = operations[index]
            if not complete:
                if wait(overlapped.event, 3000) != 0:
                    raise TimeoutError(('write' if index else 'read') + ' timed out')
                if not result(handle, C.byref(overlapped), C.byref(count), False):
                    raise C.WinError(C.get_last_error())
                pending.remove((handle, overlapped, buffer))
            response['written' if index else 'received'] = count.value
            if index == 1 and count.value != 16:
                raise ValueError('Incomplete output report')
        raw = read_buffer.raw[:operations[0][3].value]
        response['response_hex'] = raw.hex()
        marker_offset = 3 if kind == 'mouse_firmware_version' else 4
        if len(raw) != 16 or raw[0] != 9 or raw[marker_offset] != 0xc8:
            raise ValueError('Unexpected input report or success marker')
        if kind in ('firmware_version', 'mouse_firmware_version'):
            response['firmware_version_hex'] = raw[1:3].hex()
        else:
            response['raw_value'] = int.from_bytes(raw[1:3], 'big')
        response['status'] = 'complete'
    except Exception as error:
        response.update(status='error', error=str(error))
    finally:
        for handle, overlapped, buffer in pending:
            cancel(handle, C.byref(overlapped))
            result(handle, C.byref(overlapped), C.byref(W.DWORD()), True)
        for handle in events + handles:
            close(handle)
    return response


if __name__ == '__main__':
    data = query()
    path = Path(__file__).parent / 'version-query-result.json'
    path.write_text(json.dumps(data, indent=2), encoding='utf-8')
    print(json.dumps(data, indent=2))
