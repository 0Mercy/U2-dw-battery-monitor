"""Read-only Windows HID inventory and Raw Input counter for ZOWIE.

No output/feature reports or device settings are written.
"""
import argparse
import collections
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import time

K = C.WinDLL('kernel32', use_last_error=True)
H = C.WinDLL('hid', use_last_error=True)
S = C.WinDLL('setupapi', use_last_error=True)
U = C.WinDLL('user32', use_last_error=True)
P = C.c_void_p
TARGET = 'vid_04a5&pid_800a'
INVALID = C.c_void_p(-1).value

def api(lib, name, restype, args):
    f = getattr(lib, name); f.restype = restype; f.argtypes = args
    return f

class GUID(C.Structure):
    _fields_ = [('bytes', C.c_ubyte * 16)]

class Interface(C.Structure):
    _fields_ = [('cbSize', W.DWORD), ('guid', GUID), ('flags', W.DWORD), ('reserved', C.c_size_t)]

class Caps(C.Structure):
    _fields_ = [(n, W.USHORT) for n in ['usage','page','input','output','feature']] + [('reserved',W.USHORT*17)] + [(n,W.USHORT) for n in ['links','ib','iv','id','ob','ov','od','fb','fv','fd']]

create = api(K,'CreateFileW',P,[W.LPCWSTR,W.DWORD,W.DWORD,P,W.DWORD,W.DWORD,P])
close = api(K,'CloseHandle',W.BOOL,[P])
getguid = api(H,'HidD_GetHidGuid',None,[P])
getdevs = api(S,'SetupDiGetClassDevsW',P,[P,W.LPCWSTR,P,W.DWORD])
enum = api(S,'SetupDiEnumDeviceInterfaces',W.BOOL,[P,P,P,W.DWORD,P])
detail = api(S,'SetupDiGetDeviceInterfaceDetailW',W.BOOL,[P,P,P,W.DWORD,P,P])
destroy = api(S,'SetupDiDestroyDeviceInfoList',W.BOOL,[P])
preparsed = api(H,'HidD_GetPreparsedData',W.BOOL,[P,P])
freepre = api(H,'HidD_FreePreparsedData',W.BOOL,[P])
getcaps = api(H,'HidP_GetCaps',W.LONG,[P,P])
valuecaps = api(H,'HidP_GetValueCaps',W.LONG,[C.c_int,P,P,P])
buttoncaps = api(H,'HidP_GetButtonCaps',W.LONG,[C.c_int,P,P,P])
getinput = api(H,'HidD_GetInputReport',W.BOOL,[P,P,W.ULONG])

def inventory(query=False):
    guid = GUID(); getguid(C.byref(guid)); ds = getdevs(C.byref(guid),None,None,0x12)
    result=[]
    try:
        index=0
        while True:
            item=Interface(); item.cbSize=C.sizeof(item)
            if not enum(ds,None,C.byref(guid),index,C.byref(item)): break
            index+=1; size=W.DWORD()
            detail(ds,C.byref(item),None,0,C.byref(size),None)
            buf=C.create_string_buffer(size.value); C.c_uint32.from_buffer(buf).value=8 if C.sizeof(P)==8 else 6
            if not detail(ds,C.byref(item),buf,size,C.byref(size),None): continue
            path=C.wstring_at(C.addressof(buf)+4)
            if TARGET not in path.lower(): continue
            h=create(path,0,3,None,3,0,None)
            if h==INVALID:
                result.append({'path':path,'open_error':C.get_last_error()})
                continue
            pp=P()
            try:
                if not preparsed(h,C.byref(pp)): raise C.WinError(C.get_last_error())
                caps=Caps(); status=getcaps(pp,C.byref(caps))
                if status!=0x110000: raise RuntimeError(hex(status & 0xffffffff))
                row={'path':path,'usage_page':hex(caps.page),'usage':hex(caps.usage),'lengths':{t:getattr(caps,t) for t in ['input','output','feature']},'fields':[]}
                for rt,kind,prefix in [(0,'input','i'),(1,'output','o'),(2,'feature','f')]:
                    for suffix,func in [('v',valuecaps),('b',buttoncaps)]:
                        count=W.USHORT(getattr(caps,prefix+suffix))
                        if not count.value: continue
                        raw=C.create_string_buffer(72*count.value)
                        status=func(rt,raw,C.byref(count),pp)
                        if status!=0x110000: raise RuntimeError('caps '+hex(status & 0xffffffff))
                        for j in range(count.value):
                            b=raw.raw[j*72:(j+1)*72]
                            f={'type':kind,'kind':suffix,'page':hex(int.from_bytes(b[:2],'little')),'report_id':b[2],'usage_min':int.from_bytes(b[56:58],'little'),'usage_max':int.from_bytes(b[58:60],'little') if b[12] else None}
                            if suffix=='v': f.update(bit_size=int.from_bytes(b[18:20],'little'),count=int.from_bytes(b[20:22],'little'),logical_min=int.from_bytes(b[40:44],'little',signed=True),logical_max=int.from_bytes(b[44:48],'little',signed=True))
                            row['fields'].append(f)
                if query and caps.page>=0xff00 and caps.input:
                    row['queries']=[]
                    qh=create(path,0x80000000,3,None,3,0,None)
                    if qh==INVALID: row['open_error']=C.get_last_error()
                    else:
                        try:
                            for rid in sorted({f['report_id'] for f in row['fields'] if f['type']=='input'}):
                                b=C.create_string_buffer(caps.input); b[0]=rid
                                ok=getinput(qh,b,caps.input); err=C.get_last_error()
                                row['queries'].append({'report_id':rid,'ok':bool(ok),'error':None if ok else err,'hex':b.raw.hex() if ok else None})
                        finally: close(qh)
                result.append(row)
            finally:
                if pp: freepre(pp)
                close(h)
    finally: destroy(ds)
    return result

class RAWHEADER(C.Structure):
    _fields_=[('type',W.DWORD),('size',W.DWORD),('device',P),('param',C.c_size_t)]
class RAWDEVICE(C.Structure):
    _fields_=[('page',W.USHORT),('usage',W.USHORT),('flags',W.DWORD),('target',W.HWND)]
WNDPROC=C.WINFUNCTYPE(C.c_ssize_t,W.HWND,W.UINT,C.c_size_t,C.c_ssize_t)
class WNDCLASS(C.Structure):
    _fields_=[('style',W.UINT),('proc',WNDPROC),('classExtra',C.c_int),('windowExtra',C.c_int),('instance',P),('icon',P),('cursor',P),('background',P),('menu',W.LPCWSTR),('name',W.LPCWSTR)]

def listen(seconds,out):
    getdata=api(U,'GetRawInputData',W.UINT,[P,W.UINT,P,P,W.UINT])
    getname=api(U,'GetRawInputDeviceInfoW',W.UINT,[P,W.UINT,P,P])
    default=api(U,'DefWindowProcW',C.c_ssize_t,[W.HWND,W.UINT,C.c_size_t,C.c_ssize_t])
    regclass=api(U,'RegisterClassW',W.ATOM,[P])
    createwin=api(U,'CreateWindowExW',W.HWND,[W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.c_int,C.c_int,C.c_int,C.c_int,W.HWND,P,P,P])
    reginput=api(U,'RegisterRawInputDevices',W.BOOL,[P,W.UINT,W.UINT])
    peek=api(U,'PeekMessageW',W.BOOL,[P,W.HWND,W.UINT,W.UINT,W.UINT])
    dispatch=api(U,'DispatchMessageW',C.c_ssize_t,[P])
    destroywin=api(U,'DestroyWindow',W.BOOL,[W.HWND])
    counts=collections.Counter(); names={}; errors=[]
    @WNDPROC
    def wnd(hwnd,msg,wp,lp):
        if msg==0xff:
            try:
                n=W.UINT(); getdata(P(lp),0x10000003,None,C.byref(n),C.sizeof(RAWHEADER))
                b=C.create_string_buffer(n.value)
                if getdata(P(lp),0x10000003,b,C.byref(n),C.sizeof(RAWHEADER))!=0xffffffff:
                    h=RAWHEADER.from_buffer_copy(b)
                    if h.device not in names:
                        size=W.UINT(); getname(h.device,0x20000007,None,C.byref(size))
                        name=C.create_unicode_buffer(size.value+1); size.value+=1
                        getname(h.device,0x20000007,name,C.byref(size)); names[h.device]=name.value
                    counts[names[h.device]]+=1
            except Exception as e: errors.append(str(e))
        return default(hwnd,msg,wp,lp)
    wc=WNDCLASS(); wc.proc=wnd; wc.name='ZowieReadOnlyDiagnostic'
    if not regclass(C.byref(wc)): raise C.WinError(C.get_last_error())
    hwnd=createwin(0,wc.name,'',0,0,0,0,0,W.HWND(-3),None,None,None)
    if not hwnd: raise C.WinError(C.get_last_error())
    device=RAWDEVICE(1,2,0x100,hwnd)
    if not reginput(C.byref(device),1,C.sizeof(device)): raise C.WinError(C.get_last_error())
    print('LISTENING_STARTED',flush=True)
    start=time.time(); message=W.MSG()
    try:
        while time.time()-start<seconds:
            while peek(C.byref(message),None,0,0,1): dispatch(C.byref(message))
            time.sleep(.005)
    finally:
        remove=RAWDEVICE(1,2,1,None); reginput(C.byref(remove),1,C.sizeof(remove)); destroywin(hwnd)
    result={'seconds':seconds,'started':start,'counts':dict(counts),'errors':errors,'zowie_events':sum(n for name,n in counts.items() if TARGET in name.lower())}
    Path(out).write_text(json.dumps(result,indent=2),encoding='utf-8'); print(json.dumps(result,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--query',action='store_true'); parser.add_argument('--listen',type=int); parser.add_argument('--out',required=True); args=parser.parse_args()
    if args.listen: listen(args.listen,args.out)
    else:
        result=inventory(args.query); Path(args.out).write_text(json.dumps(result,indent=2),encoding='utf-8'); print(json.dumps(result,indent=2))
