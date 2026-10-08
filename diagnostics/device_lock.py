"""Coordinate vendor HID clients in the current Windows session."""
import ctypes as C
from ctypes import wintypes as W
from contextlib import contextmanager
from functools import wraps

K = C.WinDLL('kernel32', use_last_error=True)
K.CreateMutexW.argtypes = [C.c_void_p, W.BOOL, W.LPCWSTR]
K.CreateMutexW.restype = W.HANDLE
K.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
K.WaitForSingleObject.restype = W.DWORD
K.ReleaseMutex.argtypes = [W.HANDLE]
K.ReleaseMutex.restype = W.BOOL
K.CloseHandle.argtypes = [W.HANDLE]
K.CloseHandle.restype = W.BOOL


class DeviceBusyError(RuntimeError):
    pass


@contextmanager
def device_session():
    # Windows mutex ownership is recursive for the owning thread. This allows
    # a whole snapshot to hold the lock while each individual query also locks.
    handle = K.CreateMutexW(None, False, r'Local\ZowieU2DW.HidQuery.v1')
    if not handle:
        raise C.WinError(C.get_last_error())
    owned = False
    try:
        status = K.WaitForSingleObject(handle, 0)
        if status == 0x102:
            raise DeviceBusyError('Another project client is using the vendor HID interface')
        if status not in (0, 0x80):  # WAIT_OBJECT_0 / WAIT_ABANDONED
            raise C.WinError(C.get_last_error())
        owned = True
        yield
    finally:
        if owned:
            K.ReleaseMutex(handle)
        K.CloseHandle(handle)


def serialized_device(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with device_session():
            return function(*args, **kwargs)
    return wrapped
