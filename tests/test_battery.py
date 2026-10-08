"""Offline acceptance checks. HID calls are replaced by fixtures, not sent."""
import copy
import ctypes as C
from ctypes import wintypes as W
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'diagnostics'))
import battery_percentage as battery
import device_lock
import query_version as transport

spec = importlib.util.spec_from_file_location('tray_reader', ROOT / 'tray/read_battery.py')
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


class BatteryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calibration = battery.load_calibration(ROOT / 'diagnostics/full-battery-calibration.json')
        cls.snapshot = json.loads((ROOT / 'diagnostics/percentage-investigation-snapshot.json').read_text(encoding='utf-8'))

    def test_full_reference_is_estimated_not_device_full(self):
        result = battery.interpret(414, '8511', '2526', self.calibration)
        self.assertEqual(result['estimate_label'], '约 100%')
        self.assertIsNone(result['device_percentage'])
        self.assertFalse(result['full_charge_confirmed'])
        self.assertIn('unknown', result['freshness'])

    def test_range_monotonic_and_five_point_steps(self):
        values = []
        for raw in range(301, 500):
            result = battery.interpret(raw, '8511', '2526', self.calibration)
            value = result['estimated_percentage']
            if value is not None:
                self.assertTrue(0 <= value <= 100)
                self.assertEqual(value % 5, 0)
                values.append(value)
        self.assertEqual(values, sorted(values))
        self.assertEqual(len(values), 143)

    def test_invalid_values_hidden(self):
        for raw in [None, True, False, '414', 414.0, -1, 0, 300, 500, 999]:
            with self.subTest(raw=raw):
                self.assertIsNone(battery.interpret(raw, '8511', '2526', self.calibration)['estimated_percentage'])

    def test_unknown_firmware_and_offline_hidden(self):
        for receiver, mouse, status in [('0000','2526','unsupported_receiver'), ('8511','0000','disconnected_or_unknown'), ('8511','9999','unsupported_mouse')]:
            result = battery.interpret(414, receiver, mouse, self.calibration)
            self.assertEqual(result['status'], status)
            self.assertIsNone(result['estimated_percentage'])

    def test_uncalibrated_has_only_band(self):
        result = battery.interpret(414, '8511', '2526')
        self.assertIsNone(result['estimated_percentage'])
        self.assertEqual(result['firmware_band_percent'], [51, 100])

    def test_quantization_boundaries(self):
        for raw in (373, 380):
            self.assertTrue(battery.interpret(raw, '8511', '2526')['band_boundary_ambiguous'])
        self.assertEqual(battery.encode_voltage(3399, True), 370)
        self.assertEqual(battery.encode_voltage(3399, False), 368)

    def test_existing_snapshot(self):
        result = battery.interpret_snapshot(self.snapshot, self.calibration)
        self.assertEqual(result['estimated_percentage'], 100)

    def test_failed_snapshot_rejected(self):
        for key in ('receiver', 'mouse_before', 'voltage', 'mouse_after'):
            data = copy.deepcopy(self.snapshot)
            data[key]['status'] = 'error'
            with self.assertRaises(ValueError):
                battery.interpret_snapshot(data, self.calibration)

    def test_changing_mouse_version_rejected(self):
        data = copy.deepcopy(self.snapshot)
        data['mouse_after']['firmware_version_hex'] = '0000'
        with self.assertRaises(ValueError):
            battery.interpret_snapshot(data, self.calibration)

    def test_live_query_order_without_hardware(self):
        values = [self.snapshot[key] for key in ('receiver','mouse_before','voltage','mouse_after')]
        with patch.object(transport, 'query', side_effect=values) as query:
            data = battery.read_live_snapshot()
        self.assertEqual([c.args for c in query.call_args_list], [(), ('mouse_firmware_version',), ('voltage_candidate',), ('mouse_firmware_version',)])
        self.assertEqual(data['voltage'], self.snapshot['voltage'])

    def test_unsupported_receiver_stops_further_queries(self):
        with patch.object(transport, 'query', return_value={'status':'complete','firmware_version_hex':'9999'}) as query:
            with self.assertRaises(battery.UnsupportedReceiverError):
                battery.read_live_snapshot()
        self.assertEqual(query.call_count, 1)

    def test_receiver_failure_stops_further_queries(self):
        with patch.object(transport, 'query', return_value={'status':'error'}) as query:
            with self.assertRaises(RuntimeError):
                battery.read_live_snapshot()
        self.assertEqual(query.call_count, 1)

    def test_calibration_missing_rejected(self):
        with self.assertRaises(OSError):
            battery.load_calibration(ROOT / 'tests/nonexistent-calibration.json')

    def test_calibration_validation(self):
        evidence = json.loads((ROOT/'diagnostics/full-battery-calibration-evidence.json').read_text(encoding='utf-8'))
        mutations = [('receiver_firmware','9999'),('mouse_firmware','9999'),('full_led_confirmed',False),('measured_off_charger',False),('full_voltage_raw',True),('full_voltage_raw',380),('full_voltage_raw',500),('evidence_file','')]
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / self.calibration['evidence_file']).write_text(json.dumps(evidence), encoding='utf-8')
            for key, value in mutations:
                data = dict(self.calibration, **{key:value})
                path = base/'calibration.json'
                path.write_text(json.dumps(data), encoding='utf-8')
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    battery.load_calibration(path)

    def test_calibration_evidence_mismatch(self):
        evidence = json.loads((ROOT/'diagnostics/full-battery-calibration-evidence.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            path = base/'calibration.json'
            path.write_text(json.dumps(self.calibration), encoding='utf-8')
            evidence['full_voltage_raw'] = 415
            (base/self.calibration['evidence_file']).write_text(json.dumps(evidence), encoding='utf-8')
            with self.assertRaises(ValueError):
                battery.load_calibration(path)

    def test_malformed_calibration_is_classified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'diagnostics').mkdir()
            for value in ([], None, 'not an object'):
                (root/'diagnostics/full-battery-calibration.json').write_text(json.dumps(value), encoding='utf-8')
                with self.subTest(value=value), patch.object(reader,'ROOT',root), patch.object(reader,'read_live_snapshot') as query:
                    self.assertEqual(reader.read_battery()['status'],'calibration_error')
                    query.assert_not_called()

    def test_confirmation_must_be_boolean_true(self):
        evidence = json.loads((ROOT/'diagnostics/full-battery-calibration-evidence.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root/'calibration.json'
            path.write_text(json.dumps(self.calibration), encoding='utf-8')
            for section, key in [('led_confirmation','full_led_confirmed'),('removal_confirmation','removed_from_charger_confirmed')]:
                for value in ('false', 1, None):
                    changed = copy.deepcopy(evidence)
                    changed[section][key] = value
                    (root/self.calibration['evidence_file']).write_text(json.dumps(changed), encoding='utf-8')
                    with self.subTest(section=section,value=value), self.assertRaises(ValueError):
                        battery.load_calibration(path)

    def test_reader_maps_failure_without_exposing_details(self):
        cases = [(device_lock.DeviceBusyError('private'), 'device_busy'), (transport.DeviceUnavailableError('private'), 'receiver_missing'), (battery.UnsupportedReceiverError('private'), 'unsupported_receiver'), (RuntimeError('private path'), 'read_error')]
        for error, status in cases:
            with patch.object(reader, 'read_live_snapshot', side_effect=error):
                result = reader.read_battery()
            self.assertEqual(result, {'status':status, 'estimated_percentage':None})

    def test_reader_calibration_failure_before_device_access(self):
        with patch.object(reader, 'load_calibration', side_effect=ValueError()), patch.object(reader, 'read_live_snapshot') as query:
            self.assertEqual(reader.read_battery()['status'], 'calibration_error')
            query.assert_not_called()


class TransportTests(unittest.TestCase):
    def simulate(self, kind='firmware_version', reply=None, written=16, pending=False, timeout=False):
        responses = {'firmware_version':'09851100c8', 'mouse_firmware_version':'092526c8', 'voltage_candidate':'09019400c8'}
        raw = bytes.fromhex(reply if reply is not None else responses[kind]).ljust(16,b'\0')
        sent = []
        devices = [{'usage_page':'0xff04','path':'fixture-input','lengths':{'input':16}}, {'usage_page':'0xff03','path':'fixture-output','lengths':{'output':16}}]
        def read(handle, buf, size, count, ov):
            C.memmove(buf, raw, min(len(raw),16))
            C.cast(count, C.POINTER(W.DWORD)).contents.value = 16
            return not pending
        def write(handle, buf, size, count, ov):
            sent.append(buf.raw)
            C.cast(count, C.POINTER(W.DWORD)).contents.value = written
            return True
        def result(handle, ov, count, wait):
            C.cast(count, C.POINTER(W.DWORD)).contents.value = 16
            return True
        with patch.object(transport,'inventory',return_value=devices), patch.object(transport,'create',side_effect=[100,101]), patch.object(transport,'event',side_effect=[200,201]), patch.object(transport,'read',side_effect=read), patch.object(transport,'write',side_effect=write), patch.object(transport,'close') as close, patch.object(transport,'wait',return_value=0x102 if timeout else 0), patch.object(transport,'result',side_effect=result), patch.object(transport,'cancel') as cancel, patch.object(C,'get_last_error',return_value=997):
            data = transport.query.__wrapped__(kind)
        self.assertEqual(sorted(c.args[0] for c in close.call_args_list), [100,101,200,201])
        return data, sent, cancel.call_count

    def test_three_exact_whitelisted_commands(self):
        for kind, command in [('firmware_version','08b440'),('mouse_firmware_version','08b425'),('voltage_candidate','08b415')]:
            data, sent, _ = self.simulate(kind)
            self.assertEqual(sent, [bytes.fromhex(command)+bytes(13)])
            self.assertEqual(data['status'], 'complete')
        self.assertEqual(self.simulate('voltage_candidate')[0]['raw_value'],404)

    def test_random_command_rejected_before_inventory(self):
        with patch.object(transport,'inventory') as inventory:
            with self.assertRaises(ValueError):
                transport.query.__wrapped__('write_settings')
            inventory.assert_not_called()

    def test_wrong_report_or_marker_rejected(self):
        for reply in ('08851100c8', '0985110000'):
            self.assertEqual(self.simulate(reply=reply)[0]['status'],'error')

    def test_mouse_marker_uses_offset_three(self):
        self.assertEqual(self.simulate('mouse_firmware_version', reply='09252600c8')[0]['status'],'error')

    def test_short_write_rejected(self):
        self.assertEqual(self.simulate(written=8)[0]['status'],'error')

    def test_pending_read_completes(self):
        self.assertEqual(self.simulate(pending=True)[0]['status'],'complete')

    def test_timeout_cancels_and_closes(self):
        data, _, cancelled = self.simulate(pending=True,timeout=True)
        self.assertEqual(data['status'],'error')
        self.assertEqual(cancelled,1)

    def test_receiver_missing(self):
        with patch.object(transport,'inventory',return_value=[]):
            with self.assertRaises(transport.DeviceUnavailableError):
                transport.query.__wrapped__()


class LockTests(unittest.TestCase):
    def test_recursive_and_cross_process_exclusion(self):
        code = "import sys; sys.path.insert(0,sys.argv[1]); from device_lock import device_session,DeviceBusyError\ntry:\n with device_session(): print('acquired')\nexcept DeviceBusyError: print('busy')"
        with device_lock.device_session():
            with device_lock.device_session():
                child = subprocess.run([sys.executable,'-B','-c',code,str(ROOT/'diagnostics')],capture_output=True,text=True,timeout=10)
                self.assertEqual(child.returncode,0,child.stderr)
                self.assertEqual(child.stdout.strip(),'busy')
        child = subprocess.run([sys.executable,'-B','-c',code,str(ROOT/'diagnostics')],capture_output=True,text=True,timeout=10)
        self.assertEqual(child.stdout.strip(),'acquired')

    def test_exception_releases_mutex(self):
        with self.assertRaises(RuntimeError):
            with device_lock.device_session():
                raise RuntimeError('fixture')
        with device_lock.device_session():
            pass

    def test_abandoned_mutex_can_be_reacquired(self):
        code = "import sys,time; sys.path.insert(0,sys.argv[1]); from device_lock import device_session\nwith device_session():\n print('ready',flush=True)\n time.sleep(60)"
        child = subprocess.Popen([sys.executable,'-B','-c',code,str(ROOT/'diagnostics')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        handle = None
        try:
            self.assertEqual(child.stdout.readline().strip(),'ready')
            handle = device_lock.K.CreateMutexW(None,False,r'Local\ZowieU2DW.HidQuery.v1')
            self.assertTrue(handle)
            child.kill()
            child.wait(timeout=5)
            with device_lock.device_session():
                pass
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            child.stdout.close()
            child.stderr.close()
            if handle:
                device_lock.K.CloseHandle(handle)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps({'tests':result.testsRun,'failures':[(str(t),s) for t,s in result.failures],'errors':[(str(t),s) for t,s in result.errors],'passed':result.wasSuccessful(),'scope':'Offline fixtures plus real Windows mutexes; no HID commands sent'},indent=2),encoding='utf-8')
    sys.exit(not result.wasSuccessful())
