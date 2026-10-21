"""Replica extraction with shared HTTP-range cache; unchanged ZIP CRC checks.

The original extractor owns file selection and validation. Only its RemoteZip
transport is replaced to avoid repeated central-directory and overlapping block
downloads across workers. Every output still passes the original size/CRC/hash.
"""
from collections import OrderedDict
from concurrent.futures import Future,ThreadPoolExecutor
import io
from pathlib import Path
import threading
import time

import urllib.request
import urllib.error
import download_e0_replica as original


class SharedRemoteZip(original.RemoteZip):
    lock=threading.Lock()
    metadata={}
    cache=OrderedDict()
    pending={}
    scheduled=set()
    prefetch=ThreadPoolExecutor(max_workers=8)
    def __init__(self,url):
        io.RawIOBase.__init__(self)
        self.url,self.pos,self.block_size=url,0,2*1024*1024
        with self.lock:
            info=self.metadata.get(url)
            if info is None:
                with urllib.request.urlopen(urllib.request.Request(url,headers={'Range':'bytes=0-0'}),timeout=60) as r:
                    if r.status!=206:raise RuntimeError('Expected range support')
                    info=(int(r.headers['Content-Range'].split('/')[-1]),r.headers.get('ETag'))
                    r.read()
                self.metadata[url]=info
        self.size,self.etag=info

    def block(self,start):
        # File workers often wait on the same compressed block. Fetch the next
        # ranges concurrently rather than serializing network IO behind it.
        starts=[]
        with self.lock:
            for offset in range(8):
                pos=start+offset*self.block_size
                key=(self.url,self.etag,pos)
                if pos<self.size and key not in self.scheduled:
                    self.scheduled.add(key);starts.append(pos)
        for pos in starts:self.prefetch.submit(self.fetch_block,pos)
        return self.fetch_block(start)

    def fetch_block(self,start):
        key=(self.url,self.etag,start)
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key);return self.cache[key]
            leader=key not in self.pending
            future=self.pending.setdefault(key,Future())
        if not leader:return future.result()
        try:
            stop=min(self.size,start+self.block_size)-1
            for attempt in range(4):
                try:
                    headers={'Range':f'bytes={start}-{stop}'}
                    if self.etag:headers['If-Match']=self.etag
                    with urllib.request.urlopen(urllib.request.Request(self.url,headers=headers),timeout=60) as r:
                        if r.status!=206 or r.headers.get('Content-Range')!=f'bytes {start}-{stop}/{self.size}':
                            raise RuntimeError('Invalid range response')
                        data=r.read()
                    if len(data)!=stop-start+1:raise IOError('Short range response')
                    break
                except (urllib.error.URLError,OSError):
                    if attempt==3:raise
                    time.sleep(min(2**attempt,5))
            with self.lock:
                self.cache[key]=data
                while len(self.cache)>64:self.cache.popitem(last=False)
            future.set_result(data)
            return data
        except BaseException as e:
            future.set_exception(e);raise
        finally:
            with self.lock:self.pending.pop(key,None)

    def read(self,size=-1):
        end=self.size if size<0 else min(self.size,self.pos+size)
        parts=[]
        while self.pos<end:
            start=self.pos//self.block_size*self.block_size
            block=self.block(start);offset=self.pos-start
            count=min(end-self.pos,len(block)-offset)
            if count<=0:raise IOError('Invalid ZIP block offset')
            parts.append(block[offset:offset+count]);self.pos+=count
        return b''.join(parts)


if __name__=='__main__':
    original.RemoteZip=SharedRemoteZip
    original.main()
