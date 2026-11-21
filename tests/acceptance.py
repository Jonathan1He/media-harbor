"""Isolated integration test: real HTTP, SQLite, yt-dlp, aria2, FFmpeg and ffprobe."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import ROOT, TOOLS, HIDE, PYTHON, enqueue, durable, validate_tracks
from desktop import request, worker
from engine import formats, probe

def run(r):
    p=worker(r)
    events=[]
    for line in p.stdout:
        try:events.append(json.loads(line))
        except ValueError:raise AssertionError("worker wrote non-JSON output: "+repr(line[:200]))
    p.wait()
    assert events and not events[-1].get("error"),events[-1:]
    return events[-1]

def main():
    ap=argparse.ArgumentParser();ap.add_argument("base",type=Path);a=ap.parse_args()
    a.base.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=a.base) as tmp:
        w=Path(tmp);os.environ["HARBOR_DATA"]=str(w/"state")
        from PIL import Image
        v=w/"clip.mp4";big=w/"large.bmp"
        Image.new("RGB",(2400,2400),(12,52,86)).save(big)
        ff=[str(TOOLS/"ffmpeg.exe"),"-nostdin","-v","error"]
        subprocess.run(ff+["-f","lavfi","-i","testsrc2=size=320x180:rate=25","-f","lavfi","-i","sine=frequency=440","-t","3","-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac",str(v)],check=True,creationflags=HIDE)
        subprocess.run(ff+["-i",str(v),"-c","copy","-hls_list_size","0","-f","hls",str(w/"stream.m3u8")],check=True,creationflags=HIDE)
        subprocess.run(ff+["-i",str(v.resolve()),"-c","copy","-f","dash","dash.mpd"],cwd=w,check=True,creationflags=HIDE)
        requests=[]
        class Server(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_HEAD(self):self.serve(False)
            def do_GET(self):self.serve(True)
            def serve(self,body):
                name=Path(urlsplit(self.path).path).name
                f=w/name
                if not f.is_file():
                    print("Fixture requested missing path:",name,flush=True)
                    self.send_error(404);return
                size=f.stat().st_size;lo=0;hi=size-1
                header=self.headers.get("Range","")
                if header:
                    match=re.fullmatch(r"bytes=(\d+)-(\d*)",header)
                    if not match:self.send_error(416);return
                    lo=int(match[1]);hi=min(int(match[2]) if match[2] else hi,hi)
                if lo>hi:self.send_error(416);return
                self.send_response(206 if header else 200)
                self.send_header("ETag",'"fixture-'+str(size)+'"')
                self.send_header("Accept-Ranges","bytes")
                self.send_header("Content-Length",str(hi-lo+1))
                self.send_header("Content-Type",{".bmp":"image/bmp",".m3u8":"application/vnd.apple.mpegurl",".mpd":"application/dash+xml",".mp4":"video/mp4"}.get(f.suffix,"application/octet-stream"))
                if header:self.send_header("Content-Range",f"bytes {lo}-{hi}/{size}")
                self.end_headers()
                if not body:return
                requests.append((name,lo,hi))
                try:
                    with f.open("rb") as inp:
                        inp.seek(lo)
                        while lo<=hi:
                            chunk=inp.read(min(32768,hi-lo+1))
                            if not chunk:break
                            self.wfile.write(chunk);lo+=len(chunk)
                            if f==big:time.sleep(.009)
                except (ConnectionError,OSError):pass
        server=ThreadingHTTPServer(("127.0.0.1",0),Server)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        base="http://127.0.0.1:"+str(server.server_port)+"/"
        def req(name,kind,choice,key):
            return dict(source=base+name,page=base,kind=kind,choice=choice,name=name,dest=str(w/"out"),id=key,action="download",proxy="")
        try:
            for name,k,c in [("clip.mp4","video","auto"),("clip.mp4","video","audio"),("stream.m3u8","stream","auto"),("dash.mpd","stream","auto")]:
                key="id"+str(len(requests)).zfill(6)
                event=run(req(name,k,c,key))["done"]; spec=event["spec"]
                assert spec["audio"] and (spec["height"]==0 if c=="audio" else spec["height"]==180),spec
                print(name,c,spec,flush=True)
            r=req("large.bmp","image","auto","resume01")
            p=worker(r)
            start=time.monotonic()
            while time.monotonic()-start<25:
                if len([e for e in requests if e[0]=="large.bmp"])>1:break
                if p.poll() is not None:raise AssertionError(p.stdout.read())
                time.sleep(.1)
            time.sleep(1.2);p.kill();p.wait();p.stdout.close()
            before=len(requests);event=run(r)["done"]
            assert Path(event["path"]).read_bytes()==big.read_bytes()
            assert any(lo>0 for n,lo,hi in requests[before:] if n=="large.bmp"),"no ranged recovery"
            assert run(r)["done"]==event,"idempotent completion"
            print("killed worker: ranged recovery; exact hash; idempotent result",flush=True)
            times=[]
            for single in (True,False,False,True):
                n=len(times);r=req("large.bmp","image","auto","bench00"+str(n))
                r["single"]=single;start=time.monotonic()
                done=run(r)["done"]
                times.append(round(time.monotonic()-start,2))
                assert Path(done["path"]).read_bytes()==big.read_bytes()
            print("fixture bytes",big.stat().st_size,"single/multi/multi/single seconds",times,flush=True)
            assert durable("https://www.bilibili.com/video/BVtest?p=2&token=x").endswith("?p=2")
            assert formats({"formats":[{"format_id":"v","url":"https://media.example/v","height":1080,"fps":60,"acodec":"none"},{"format_id":"4k","url":"https://media.example/4","height":2160,"fps":30}]},"auto").startswith("v+")
            print("1080p selection, URL redaction passed",flush=True)
        finally:server.shutdown();server.server_close()
if __name__=="__main__":main()

