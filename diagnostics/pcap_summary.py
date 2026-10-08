"""Summarize USBPcap packets without printing unrelated payloads."""
import collections
import json
from pathlib import Path
import struct
import sys

def summarize(path):
    data=Path(path).read_bytes()
    if len(data)<24 or data[:4]!=bytes.fromhex('d4c3b2a1'): raise ValueError('Not a little-endian PCAP')
    if struct.unpack_from('<I',data,20)[0]!=249: raise ValueError('Not USBPcap')
    off=24;routes=collections.Counter();payloads=collections.defaultdict(collections.Counter);control=[];count=0
    while off+16<=len(data):
        ts,us,size,orig=struct.unpack_from('<IIII',data,off)
        if off+16+size>len(data): break
        packet=data[off+16:off+16+size];off+=16+size
        if len(packet)<27: continue
        hlen,irp,status,func,info,bus,dev,ep,transfer,n=struct.unpack_from('<HQIHBHHBBI',packet)
        payload=packet[hlen:];count+=1
        key=f'bus={bus} dev={dev} ep={ep:02x} type={transfer} info={info} status={status:08x} bytes={len(payload)}'
        routes[key]+=1
        if transfer==2: control.append({'time':ts+us/1e6,'bus':bus,'device':dev,'stage':packet[27] if hlen>27 else None,'status':hex(status),'data':payload[:128].hex()})
        if transfer==1 and info&1 and payload and bus==4 and dev==1: payloads[f'{ep:02x}'].update([payload.hex()])
    return {'file':str(path),'size':len(data),'records':count,'unparsed_tail':len(data)-off,'routes':dict(routes),'control':control[:50],'interrupt_payloads':{ep:{'unique':len(c),'top':c.most_common(12)} for ep,c in payloads.items()}}

if __name__=='__main__':
    result=summarize(sys.argv[1]);text=json.dumps(result,indent=2)
    if len(sys.argv)>2: Path(sys.argv[2]).write_text(text,encoding='utf-8')
    print(text)
