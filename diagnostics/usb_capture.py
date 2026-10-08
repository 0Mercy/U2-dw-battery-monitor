"""Bounded USBPcap driver capture; requires administrator rights.

Filters one USB device, stops filtering, cancels pending I/O and closes cleanly.
Does not submit USB requests or send HID output reports to the target device.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import struct
import time
from hid_probe import K, P, api, create, close, INVALID

class Overlapped(C.Structure):
    _fields_=[('internal',C.c_size_t),('internalHigh',C.c_size_t),('offset',W.DWORD),('offsetHigh',W.DWORD),('event',P)]

event=api(K,'CreateEventW',P,[P,W.BOOL,W.BOOL,W.LPCWSTR])
reset=api(K,'ResetEvent',W.BOOL,[P])
wait=api(K,'WaitForSingleObject',W.DWORD,[P,W.DWORD])
ioctl=api(K,'DeviceIoControl',W.BOOL,[P,W.DWORD,P,W.DWORD,P,W.DWORD,P,P])
read=api(K,'ReadFile',W.BOOL,[P,P,W.DWORD,P,P])
result=api(K,'GetOverlappedResult',W.BOOL,[P,P,P,W.BOOL])
cancel=api(K,'CancelIoEx',W.BOOL,[P,P])

def control(h,code,data=b'',outsize=0):
    ov=Overlapped();ov.event=event(None,True,False,None)
    ib=C.create_string_buffer(data) if data else None
    ob=C.create_string_buffer(outsize) if outsize else None
    n=W.DWORD()
    try:
        if not ioctl(h,code,ib,len(data),ob,outsize,C.byref(n),C.byref(ov)):
            err=C.get_last_error()
            if err!=997: raise C.WinError(err)
            if wait(ov.event,3000)!=0:
                cancel(h,C.byref(ov));result(h,C.byref(ov),C.byref(n),True)
                raise TimeoutError('USBPcap control timed out')
            if not result(h,C.byref(ov),C.byref(n),False): raise C.WinError(C.get_last_error())
        return ob.raw[:n.value] if ob else b''
    finally: close(ov.event)

def capture(bus,address,seconds,out):
    h=create('\\\\.\\USBPcap'+str(bus),0xc0000000,0,None,3,0x40000000,None)
    if h==INVALID: raise C.WinError(C.get_last_error())
    ov=Overlapped();ov.event=event(None,True,False,None)
    active=False;pending=False;meta={'bus':bus,'address':address,'seconds':seconds,'status':'starting'}
    status=Path(str(out)+'.json')
    try:
        hub=control(h,0x22200c,outsize=4096)
        meta['hub_link']=hub.decode('utf-16-le',errors='replace').strip('\x00')
        control(h,0x226010,struct.pack('<I',65535))
        control(h,0x226000,struct.pack('<I',1024*1024))
        bits=[0]*4;bits[address//32]|=1<<(address%32)
        control(h,0x22e004,struct.pack('<IIIIB',*bits,0));active=True
        meta.update(status='capturing',started=time.time());status.write_text(json.dumps(meta,indent=2),encoding='utf-8')
        buf=C.create_string_buffer(65536);n=W.DWORD();total=0;end=time.monotonic()+seconds
        with Path(out).open('wb') as f:
            while time.monotonic()<end:
                if not pending:
                    reset(ov.event)
                    if read(h,buf,len(buf),C.byref(n),C.byref(ov)):
                        f.write(buf.raw[:n.value]);f.flush();total+=n.value;continue
                    err=C.get_last_error()
                    if err!=997: raise C.WinError(err)
                    pending=True
                if wait(ov.event,100)==0:
                    if not result(h,C.byref(ov),C.byref(n),False): raise C.WinError(C.get_last_error())
                    pending=False;f.write(buf.raw[:n.value]);f.flush();total+=n.value
            control(h,0x22e008);active=False
            if pending:
                cancel(h,C.byref(ov))
                if result(h,C.byref(ov),C.byref(n),True): f.write(buf.raw[:n.value]);total+=n.value
                pending=False
        meta.update(status='complete',bytes=total,finished=time.time())
    except Exception as e:
        meta.update(status='error',error=str(e));raise
    finally:
        if active:
            try: control(h,0x22e008)
            except Exception: pass
        if pending: cancel(h,C.byref(ov));result(h,C.byref(ov),C.byref(W.DWORD()),True)
        close(ov.event);close(h);status.write_text(json.dumps(meta,indent=2),encoding='utf-8')

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--bus',type=int,required=True);a.add_argument('--address',type=int,required=True);a.add_argument('--seconds',type=int,default=30);a.add_argument('--out',type=Path,required=True);args=a.parse_args()
    if not 1<=args.address<=127: a.error('address must be 1..127')
    capture(args.bus,args.address,args.seconds,args.out)
