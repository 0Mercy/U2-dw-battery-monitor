"""Execute extracted firmware functions in an offline ARM emulator.

No device I/O. Hardware status inputs are supplied explicitly. This verifies
firmware control flow and arithmetic, not physical state-of-charge accuracy.
"""
import hashlib
import json
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / '_analysis_deps'))
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import (
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC,
)

BATTERY = 0x200000A8
STOP = 0x18000
HANDLERS = {
    0x2140: 'startup_three_leds',
    0x22EC: 'startup_two_leds',
    0x225C: 'startup_one_led',
    0x237C: 'low_battery_blink',
    0x2444: 'leds_off',
    0x1FB0: 'charging_two_solid_third_pulsing',
    0x20F0: 'charging_one_solid_second_pulsing',
    0x20B4: 'charging_first_pulsing',
    0x1F18: 'charging_full_three_solid',
    0x200C: 'special_charging_pattern',
    0x21D0: 'special_wireless_pattern',
}


class Firmware:
    def __init__(self, binary):
        self.machine = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        self.machine.mem_map(0, 0x20000)
        self.machine.mem_write(0, binary)
        self.machine.mem_map(0x20000000, 0x10000)
        self.machine.hook_add(UC_HOOK_CODE, self.on_instruction)
        self.selected = None
        self.pin9 = 0

    def on_instruction(self, machine, address, size, user_data):
        if address in HANDLERS:
            self.selected = HANDLERS[address]
            machine.emu_stop()
        elif address == 0x30AC:
            # Exclude the separate special indication mode.
            machine.reg_write(UC_ARM_REG_R0, 0)
            machine.reg_write(UC_ARM_REG_PC, machine.reg_read(UC_ARM_REG_LR))
        elif address == 0x2A1A:
            if machine.reg_read(UC_ARM_REG_R0) != 9:
                raise RuntimeError('Unexpected GPIO read in LED selector')
            machine.reg_write(UC_ARM_REG_R0, self.pin9)
            machine.reg_write(UC_ARM_REG_PC, machine.reg_read(UC_ARM_REG_LR))

    def run(self, address, r0=0, r1=0, r2=0):
        for register, value in (
            (UC_ARM_REG_SP, 0x2000FFF0), (UC_ARM_REG_LR, STOP | 1),
            (UC_ARM_REG_R0, r0), (UC_ARM_REG_R1, r1), (UC_ARM_REG_R2, r2),
        ):
            self.machine.reg_write(register, value)
        self.machine.emu_start(address | 1, STOP, count=5000)
        if self.selected is None and self.machine.reg_read(UC_ARM_REG_PC) != STOP:
            raise RuntimeError('Firmware execution did not finish')
        return self.machine.reg_read(UC_ARM_REG_R0)

    def select(self, adc, charging=False, startup=True, pin9=0, gate=0,
               full_counter=0, previous_mode=0):
        self.machine.mem_write(BATTERY, bytes(0x40))
        self.machine.mem_write(BATTERY + 3, bytes([int(startup), previous_mode]))
        self.machine.mem_write(BATTERY + 0x1A, struct.pack('<H', full_counter))
        self.selected = None
        self.pin9 = pin9
        self.run(0x247C, adc, int(charging), gate)
        if self.selected is None:
            raise RuntimeError('No LED handler selected')
        return self.selected

    def encoded_voltage(self, adc, correction_enabled=True):
        self.machine.mem_write(BATTERY, bytes(0x40))
        self.machine.mem_write(BATTERY + 0xA, bytes([int(not correction_enabled)]))
        self.selected = None
        mv = self.run(0x175C, adc, 1)
        encoded = self.run(0x2908) + 300
        return mv, encoded


def main():
    binary = (HERE / 'firmware-analysis/Mouse_Tx_U2DW.bin').read_bytes()
    firmware = Firmware(binary)
    transitions = {}
    for name, arguments in (
        ('startup', {'startup': True}),
        ('normal_use', {'startup': False}),
        ('charging', {'charging': True}),
    ):
        changes = []
        previous = None
        for adc in range(4096):
            handler = firmware.select(adc, **arguments)
            if handler != previous:
                changes.append({'adc': adc, 'handler': handler})
                previous = handler
        transitions[name] = changes

    arithmetic_mismatches = []
    encoded_to_adc = {}
    for adc in range(4096):
        mv, encoded = firmware.encoded_voltage(adc)
        expected_mv = adc * 0x3CA50 // 0x38000
        expected = min(500, max(300, expected_mv // 10))
        if expected in (368, 369):
            expected = 370
        if (mv, encoded) != (expected_mv, expected):
            arithmetic_mismatches.append({'adc': adc, 'actual': [mv, encoded],
                                          'expected': [expected_mv, expected]})
        encoded_to_adc.setdefault(str(encoded), []).append(adc)

    full_cases = []
    for adc, pin9, gate, counter, mode in (
        (3785, 1, 0, 3999, 0),
        (3786, 0, 0, 3999, 0),
        (3786, 1, 1, 3999, 0),
        (3786, 1, 0, 3998, 0),
        (3786, 1, 0, 3999, 0),
        (3511, 0, 1, 0, 6),
        (3510, 1, 0, 3999, 6),
    ):
        full_cases.append({
            'adc': adc, 'pin9': pin9, 'gate': gate,
            'counter_before': counter, 'previous_mode': mode,
            'handler': firmware.select(adc, charging=True, pin9=pin9, gate=gate,
                                       full_counter=counter, previous_mode=mode),
        })
    report = {
        'firmware_sha256': hashlib.sha256(binary).hexdigest(),
        'emulator': 'Unicorn 2.1.4 ARM Thumb M-class',
        'adc_values_per_sweep': 4096,
        'led_transitions': transitions,
        'conversion_mismatches': arithmetic_mismatches,
        'full_detection_cases': full_cases,
        'encoded_to_adc_intervals': {
            key: [min(values), max(values)] for key, values in encoded_to_adc.items()
        },
        'limits': [
            'Hardware status inputs were simulated; no device commands were sent.',
            'Percentages require matching these LED branches to the user manual.',
            'This does not measure actual remaining capacity or validate interpolation.',
            'ADC 0 and invalid startup values are included for control-flow coverage.',
        ],
    }
    path = HERE / 'battery-threshold-emulation.json'
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items()
                      if key != 'encoded_to_adc_intervals'}, indent=2))


if __name__ == '__main__':
    main()
