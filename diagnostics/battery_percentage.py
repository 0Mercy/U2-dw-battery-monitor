"""Infer manufacturer LED bands and optionally estimate a battery percentage.

Standard library only; offline interpretation or one-shot read-only HID queries.
No background polling. The continuous estimate is a proposed interpolation,
NOT a percentage supplied by ZOWIE.
See BATTERY_PERCENTAGE.md for evidence and limitations.
"""
import argparse
import json
from pathlib import Path
import time

ADC_SCALE_NUMERATOR = 0x3CA50
ADC_SCALE_DENOMINATOR = 0x38000
SUPPORTED_RECEIVER = '8511'
SUPPORTED_MOUSE = '2526'


def adc_to_millivolts(adc):
    return adc * ADC_SCALE_NUMERATOR // ADC_SCALE_DENOMINATOR


def encode_voltage(adc, correction_enabled):
    raw = min(500, max(300, adc_to_millivolts(adc) // 10))
    if correction_enabled and raw in (368, 369):
        return 370
    return raw


def percentage_band(adc):
    # LED voltage bands, not independently measured capacity bounds.
    if adc <= 3398:
        return 0, 10
    if adc <= 3446:
        return 11, 25
    if adc <= 3510:
        return 26, 50
    # The base does not expose the full-charge signal, so include 100 here.
    return 51, 100


def load_calibration(path):
    path = Path(path)
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Calibration must be a JSON object')
    if data.get('receiver_firmware') != SUPPORTED_RECEIVER:
        raise ValueError('Calibration receiver firmware must be 8511')
    if data.get('mouse_firmware') != SUPPORTED_MOUSE:
        raise ValueError('Calibration mouse firmware must be 2526')
    if data.get('full_led_confirmed') is not True:
        raise ValueError('Full-charge LED observation has not been confirmed')
    if data.get('measured_off_charger') is not True:
        raise ValueError('Full reference must be sampled after removal from charger')
    raw = data.get('full_voltage_raw')
    if type(raw) is not int or not 381 <= raw < 500:
        raise ValueError('Invalid full reference voltage')
    if not data.get('evidence_file'):
        raise ValueError('Calibration needs an observation evidence file')
    evidence_path = path.parent / data['evidence_file']
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    if not isinstance(evidence, dict):
        raise ValueError('Calibration evidence must be a JSON object')
    if evidence.get('full_voltage_raw') != raw:
        raise ValueError('Calibration voltage does not match its observation evidence')
    led = evidence.get('led_confirmation')
    removal = evidence.get('removal_confirmation')
    if not isinstance(led, dict) or led.get('full_led_confirmed') is not True:
        raise ValueError('Observation evidence lacks full-charge LED confirmation')
    if not isinstance(removal, dict) or removal.get('removed_from_charger_confirmed') is not True:
        raise ValueError('Observation evidence lacks charger removal confirmation')
    return data


def interpolate(millivolts, full_raw):
    # Zero is an operating cutoff approximation; 10/25/50 follow LED thresholds.
    anchors = [(adc_to_millivolts(3140), 0),
               (adc_to_millivolts(3398), 10),
               (adc_to_millivolts(3446), 25),
               (adc_to_millivolts(3510), 50),
               (full_raw * 10, 100)]
    if millivolts <= anchors[0][0]:
        return 0.0
    for (left_v, left_p), (right_v, right_p) in zip(anchors, anchors[1:]):
        if millivolts <= right_v:
            return left_p + (millivolts - left_v) * (right_p - left_p) / (right_v - left_v)
    return 100.0


def interpret(raw, receiver_version, mouse_version, calibration=None):
    result = {'raw_voltage': raw, 'receiver_firmware': receiver_version,
              'mouse_firmware': mouse_version, 'device_percentage': None,
              'estimated_percentage': None}
    if receiver_version != SUPPORTED_RECEIVER:
        return dict(result, status='unsupported_receiver')
    if mouse_version == '0000':
        return dict(result, status='disconnected_or_unknown')
    if mouse_version != SUPPORTED_MOUSE:
        return dict(result, status='unsupported_mouse')
    if type(raw) is not int or not 300 < raw < 500:
        return dict(result, status='invalid_or_saturated_voltage')
    candidates = [adc for adc in range(1, 4096)
                  if any(encode_voltage(adc, flag) == raw for flag in (False, True))]
    if not candidates:
        return dict(result, status='unrecognized_voltage')
    lower = min(percentage_band(adc)[0] for adc in candidates)
    upper = max(percentage_band(adc)[1] for adc in candidates)
    result.update(status='cached_voltage_only', inferred_volts=raw / 100,
                  adc_interval=[min(candidates), max(candidates)],
                  firmware_band_percent=[lower, upper],
                  band_boundary_ambiguous=percentage_band(min(candidates)) !=
                                          percentage_band(max(candidates)),
                  full_charge_confirmed=False,
                  freshness='Receiver cache age is unknown')
    if calibration is not None:
        estimate = interpolate(raw * 10, calibration['full_voltage_raw'])
        # Five-point steps avoid implying one-percent measurement accuracy.
        rounded = int(5 * round(estimate / 5))
        result['estimated_percentage'] = min(100, max(0, rounded))
        result['estimate_method'] = 'Unvalidated piecewise voltage interpolation'
        result['estimate_label'] = f"约 {result['estimated_percentage']}%"
        result['calibration_evidence'] = calibration['evidence_file']
    else:
        result['estimate_unavailable_reason'] = 'A confirmed full reference is required'
    return result


class UnsupportedReceiverError(ValueError):
    pass


def read_live_snapshot():
    from device_lock import device_session
    from query_version import query
    with device_session():
        receiver = query()
        if receiver.get('status') != 'complete':
            raise RuntimeError('Receiver query failed')
        if receiver.get('firmware_version_hex') != SUPPORTED_RECEIVER:
            raise UnsupportedReceiverError('Live query is restricted to receiver firmware 8511')
        return {'time': time.time(), 'receiver': receiver,
                'mouse_before': query('mouse_firmware_version'),
                'voltage': query('voltage_candidate'),
                'mouse_after': query('mouse_firmware_version')}


def interpret_snapshot(data, calibration=None):
    keys = ('receiver', 'mouse_before', 'voltage', 'mouse_after')
    if any(data[key].get('status') != 'complete' for key in keys):
        raise ValueError('Snapshot contains a failed query')
    before = data['mouse_before']['firmware_version_hex']
    after = data['mouse_after']['firmware_version_hex']
    if before != after:
        raise ValueError('Mouse state changed while taking the snapshot')
    result = interpret(data['voltage']['raw_value'],
                       data['receiver']['firmware_version_hex'], after, calibration)
    result['snapshot_time'] = data['time']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--snapshot', type=Path,
                        help='Saved serial receiver/mouse_before/voltage/mouse_after queries')
    source.add_argument('--live', action='store_true',
                        help='Read once using the three identified read-only HID queries')
    parser.add_argument('--calibration', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    calibration = load_calibration(args.calibration) if args.calibration else None
    if args.live:
        data = read_live_snapshot()
    else:
        data = json.loads(args.snapshot.read_text(encoding='utf-8'))
    result = interpret_snapshot(data, calibration)
    result['snapshot_file'] = str(args.snapshot) if args.snapshot else None
    if args.live:
        result['source_queries'] = data
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(output, encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
