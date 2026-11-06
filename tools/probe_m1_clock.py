"""Read-only macOS continuous-clock availability probe; never changes system time."""
import argparse
import ctypes
import json
from pathlib import Path
import sys
import time


def probe():
    result = {'platform_probe': 'macOS_only', 'system_sleep_performed': False,
              'system_clock_changed': False, 'file_service_started': False,
              'sleep_behavior_reference': 'https://developer.apple.com/documentation/kernel/1646199-mach_continuous_time',
              'actual_sleep_resume_and_expiry': 'not_tested'}
    if sys.platform != 'darwin':
        return {**result, 'api_status': 'not_tested'}
    try:
        library = ctypes.CDLL('/usr/lib/libSystem.B.dylib')
        clock = library.mach_continuous_time
        clock.argtypes, clock.restype = [], ctypes.c_uint64
        class Timebase(ctypes.Structure):
            _fields_ = [('numer', ctypes.c_uint32), ('denom', ctypes.c_uint32)]
        conversion = library.mach_timebase_info
        conversion.argtypes, conversion.restype = [ctypes.POINTER(Timebase)], ctypes.c_int
        base = Timebase()
        if conversion(ctypes.byref(base)) != 0 or not base.denom:
            raise ValueError('timebase unavailable')
        before = clock()
        time.sleep(.02)
        after = clock()
        seconds = (after-before)*base.numer/base.denom/1e9
        return {**result, 'api_status': 'available', 'api': 'mach_continuous_time',
                'positive_progress': after > before, 'short_wait_observed': .005 < seconds < 2,
                'sleep_inclusive_property': 'documented_by_vendor_not_physically_tested'}
    except (AttributeError, OSError, ValueError):
        return {**result, 'api_status': 'unavailable', 'next_step': 'needs_action: do not promise suspend-safe expiry'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    result = probe()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
