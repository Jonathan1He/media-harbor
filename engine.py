"""One isolated worker per analysis/download. Input and progress are JSON lines."""
import ctypes
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlsplit
import urllib.request
from core import TOOLS, HIDE, durable, error_text, platform, safe_name, url

def emit(**data):
    print(json.dumps(data, ensure_ascii=True), flush=True)

def private_job():
    # Terminating the worker must also terminate any FFmpeg/aria2 children.
    if os.name != "nt":
        return
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k.GetCurrentProcess.restype = wintypes.HANDLE
    class Basic(ctypes.Structure):
        _fields_ = [("a",ctypes.c_int64),("b",ctypes.c_int64),("flags",wintypes.DWORD),
                    ("min",ctypes.c_size_t),("max",ctypes.c_size_t),("count",wintypes.DWORD),
                    ("mask",ctypes.c_size_t),("priority",wintypes.DWORD),("sched",wintypes.DWORD)]
    class Limits(ctypes.Structure):
        _fields_ = [("basic",Basic),("io",ctypes.c_uint64*6),("sizes",ctypes.c_size_t*4)]
    j = k.CreateJobObjectW(None,None)
    limits = Limits()
    limits.basic.flags = 0x2000
    if not (j and k.SetInformationJobObject(j,9,ctypes.byref(limits),ctypes.sizeof(limits)) and k.AssignProcessToJobObject(j,k.GetCurrentProcess())):
        raise OSError("无法创建可安全暂停的下载进程组")

class Log:
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass

def options(req):
    opts = dict(quiet=True,no_warnings=True,logger=Log(),noplaylist=True,playlistend=1,
                cachedir=False,socket_timeout=18,retries=3,fragment_retries=3,
                skip_unavailable_fragments=False,concurrent_fragment_downloads=4,
                ffmpeg_location=str(TOOLS),windowsfilenames=True,
                js_runtimes={"node":{"path":str(TOOLS/"node.exe")}},remote_components=set())
    if req.get("proxy") is not None and req["proxy"]!="system":
        opts["proxy"] = req["proxy"]
    if req.get("page"):
        # No arbitrary headers are accepted from browser messages.
        opts["http_headers"] = {"Referer":url(req["page"])}
    return opts

def bilibili_post(ydl, req, match):
    from yt_dlp.extractor.bilibili import BiliBiliIE
    from yt_dlp.networking import Request
    from yt_dlp.networking.exceptions import RequestError

    post_id = match.group(1)
    identity = {"bvid": post_id} if post_id.startswith("BV") else {"aid": post_id[2:]}
    page = durable(req["source"])
    part_number = parse_qs(urlsplit(page).query, keep_blank_values=True).get("p", ["1"])[0]
    if not re.fullmatch(r"[1-9][0-9]{0,6}", part_number):
        raise ValueError("无效的 B 站分 P 编号")

    client_headers = {"User-Agent": "MediaHarbor/0.1", "Referer": page}

    def read(route, **params):
        endpoint = "https://api.bilibili.com/x/" + route + "?" + urlencode({**identity, **params})
        headers = {**client_headers, "Accept": "application/json"}
        with ydl.urlopen(Request(endpoint, headers=headers)) as response:
            payload = json.load(response)
        if payload.get("code") != 0:
            raise ValueError(f"B 站返回 {payload.get('code')}：{payload.get('message') or '无法读取资源'}")
        return payload["data"]

    parts = read("player/pagelist")
    part = next((p for p in parts or [] if str(p.get("page")) == part_number), None)
    if not part:
        raise ValueError(f"B 站未提供第 {part_number} P")
    play = read("player/playurl", cid=part["cid"], qn=80, fnval=16)
    if not play or play.get("is_drm") or play.get("is_preview"):
        raise ValueError("B 站未向当前会话提供可保存的完整视频")
    dash = play.get("dash") or {}
    if any(track.get("ContentProtection") or track.get("contentProtection") or track.get("drm")
           for kind in ("video", "audio") for track in dash.get(kind) or []):
        raise ValueError("B 站提供的是受保护的音视频轨道")
    streams = BiliBiliIE(ydl).extract_formats(play)
    if not any(f.get("url") and f.get("vcodec") != "none" for f in streams):
        raise ValueError("B 站未向当前会话提供视频轨道，可在官网正常播放后使用「用当前播放器重试」")

    # A missing title must not discard media the playback service already supplied.
    try:
        details = read("web-interface/view") or {}
    except (RequestError, ValueError, OSError):
        details = {}
    supplied_title = req.get("name")
    title = details.get("title") or (supplied_title if supplied_title and supplied_title != "媒体" else post_id)
    if len(parts) > 1:
        title += f" · P{part_number} " + (part.get("part") or "").strip()
    info = dict(id=f"{post_id}-p{part_number}-{part['cid']}", title=title, thumbnail=details.get("pic"),
                webpage_url=page, http_headers=client_headers, formats=streams)
    ydl.sort_formats(info)
    return info

def meta(ydl,req):
    tracks = req.get("tracks")
    if tracks:
        from core import validate_tracks
        fs=[]
        for t in validate_tracks(req["page"],tracks):
            fs.append(dict(url=t["url"],format_id=str(len(fs)),ext=t["ext"],height=t["height"],fps=t["fps"],
                           vcodec="none" if t["kind"]=="audio" else "unknown",
                           acodec="none" if t["kind"]=="video" else "unknown"))
        return {"id":req.get("media_id") or req["page"],"title":req["name"],"formats":fs}
    if req["kind"] in ("video","audio","image"):
        from mimetypes import guess_extension
        path=Path(unquote(urlsplit(req["source"]).path))
        ext=path.suffix[1:].lower()
        if not re.fullmatch(r"[a-z0-9]{1,6}",ext) or ext in ("php","aspx","html","cgi","ashx"):
            ext=(guess_extension(req.get("mime","").split(";")[0]) or {"audio":".m4a","video":".mp4","image":".img"}[req["kind"]]).strip(".")
        return {"id":req["source"].split("?")[0],"title":req.get("name") or path.stem,"url":req["source"],"ext":ext,"format_id":"direct"}
    source = url(req["source"])
    parsed = urlsplit(source)
    if parsed.hostname in {"www.bilibili.com", "m.bilibili.com", "bilibili.com"}:
        post = re.fullmatch(r"/video/(BV[0-9A-Za-z]{10}|av[0-9]+)/?", parsed.path)
        if post:
            return bilibili_post(ydl, req, post)
    return ydl.extract_info(source, download=False)

def rows(info):
    fs=[f for f in info.get("formats",[]) if f.get("url") and not f.get("has_drm") and f.get("vcodec")!="none" and f.get("ext")!="mhtml" and f.get("protocol")!="mhtml"]
    # Keep each actual frame-rate/height combination. yt-dlp orders best formats last.
    choices={}
    for f in fs:
        h,fps=int(f.get("height") or 0),float(f.get("fps") or 0)
        if h:
            choices[h,fps]=dict(id=f["format_id"],height=h,fps=fps,label=f"{h}p"+(f" · {fps:g} fps" if fps else ""))
    return sorted(choices.values(),key=lambda x:(x["height"],x["fps"]),reverse=True)

def formats(info, choice):
    if choice=="audio":
        return "bestaudio/best"
    if choice.startswith("id:"):
        fid=choice[3:]
        if not re.fullmatch(r"[\w.-]+",fid) or not any(f.get("format_id")==fid and not f.get("has_drm") for f in info.get("formats",[])):
            raise ValueError("所选画质已变更，请重新解析")
        target=next(f for f in info["formats"] if f.get("format_id")==fid)
        return fid+"+bestaudio/"+fid if target.get("acodec")=="none" else fid
    if choice!="auto":
        raise ValueError("无效画质选择")
    selected=next((f for f in rows(info) if f["height"]<=1080),None)
    if selected:
        return formats(info,"id:"+selected["id"])
    if rows(info):
        raise ValueError("仅提供高于 1080p 的版本，请手动选择画质")
    return "bestvideo*+bestaudio/best"

def probe(file):
    result=subprocess.run([str(TOOLS/"ffprobe.exe"),"-v","error","-show_entries","stream=codec_type,width,height,avg_frame_rate:format=duration","-of","json",str(file)],capture_output=True,creationflags=HIDE,timeout=60)
    if result.returncode:
        raise ValueError("成品文件未通过媒体完整性检查")
    data=json.loads(result.stdout)
    streams=data.get("streams",[])
    from fractions import Fraction
    video=next((s for s in streams if s.get("codec_type")=="video"),{})
    rate=video.get("avg_frame_rate","0/1")
    return dict(height=video.get("height",0),fps=round(float(Fraction(rate)),2) if rate!="0/0" else 0,
                audio=any(s.get("codec_type")=="audio" for s in streams),duration=data.get("format",{}).get("duration"))

def validators(req,link):
    proxies = None if req.get("proxy","system")=="system" else {k:req["proxy"] for k in ("http","https")}
    opener=urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
    try:
        request=urllib.request.Request(link,method="HEAD",headers={"Referer":req["page"],"Accept-Encoding":"identity"})
        with opener.open(request,timeout=8) as res:
            hdr=res.headers
            version=hdr.get("ETag") or hdr.get("Last-Modified")
            return [version,hdr.get("Content-Length")] if version else None
    except OSError:
        return None

def direct_transfer(req, info, work):
    """Read aria2 progress separately from the worker JSON protocol."""
    target=work/("media."+info["ext"])
    if target.is_file():return
    partial=target.with_suffix(target.suffix+".part")
    if partial.exists() and not Path(str(partial)+".aria2").exists():
        partial.unlink()
    args=[str(TOOLS/"aria2c.exe"),"--no-conf","--input-file=-","--dir="+str(work.resolve()),
          "--continue=true","--auto-file-renaming=false","--allow-overwrite=true",
          "--max-connection-per-server=4","--split=4","--min-split-size=1M","--file-allocation=none",
          "--auto-save-interval=1","--max-tries=3","--retry-wait=1","--timeout=25","--connect-timeout=15",
          "--summary-interval=1","--enable-color=false","--console-log-level=warn","--download-result=hide",
          "--referer="+durable(req["page"])]
    proxy=req.get("proxy","system")
    if proxy=="system":
        proxy=urllib.request.getproxies().get(urlsplit(req["source"]).scheme,"")
        if urllib.request.proxy_bypass(urlsplit(req["source"]).hostname):proxy=""
    if proxy and "://" not in proxy:proxy="http://"+proxy
    args.append("--all-proxy="+proxy)
    proc=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                          creationflags=HIDE,text=True,encoding="utf8",errors="replace")
    proc.stdin.write(req["source"]+"\n  out="+partial.name+"\n");proc.stdin.close()
    reason=""
    for line in proc.stdout:
        match=re.search(r"\((\d+%)\).*?\bDL:([\d.]+\w*)",line)
        if match:emit(progress=match[1]+" · "+match[2]+"/s")
        error=re.search(r"(?:status=|errorCode=)(\d+)",line)
        if error:reason=error[1]
    proc.stdout.close()
    if proc.wait()!=0:raise ValueError("直链下载失败"+("（"+reason+"）" if reason else "")+"，可返回原网页刷新资源后重试")
    partial.rename(target)

def run(req):
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError
    opts=options(req)
    with YoutubeDL(opts) as inspector:
        info=meta(inspector,req)
    if info and info.get("_type")=="playlist":
        entries=list(info.get("entries") or [])
        info=entries[0] if len(entries)==1 else None
    if not info:
        raise ValueError("请打开具体视频或当前分 P，再次解析")
    if req["action"]=="inspect":
        choices=rows(info)
        emit(info=dict(title=info.get("title","媒体"),thumbnail=info.get("thumbnail"),choices=choices,
                       default=next((c["label"] for c in choices if c["height"]<=1080),"源文件" if not choices else "请选择画质")))
        return
    dest=Path(req["dest"])
    dest.mkdir(parents=True,exist_ok=True)
    stage=dest/(".media-harbor-"+req["id"])
    stage.mkdir(exist_ok=True)
    receipt=stage/"complete.json"
    if receipt.exists():
        r=json.loads(receipt.read_text("utf8"))
        if Path(r["path"]).is_file() and Path(r["path"]).stat().st_size==r["bytes"]:
            emit(done=r)
            return
    direct="formats" not in info and req["kind"] in ("video","audio","image")
    selector="best" if direct else formats(info,req["choice"])
    signature=[str(info["id"]),selector,req["choice"]]
    if not direct:
        signature.extend([(str(f.get("format_id")),f.get("filesize"),f.get("height"),f.get("vcodec")) for f in info.get("formats",[]) if not f.get("has_drm")])
    else:
        stamp=validators(req,req["source"])
        signature.append(stamp or str(time.time_ns()))
    import hashlib
    token=hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()[:16]
    work=stage/token
    work.mkdir(exist_ok=True)
    last=[0.]
    def progress(d):
        now=time.monotonic()
        if now-last[0]<0.25 and d["status"]!="finished":
            return
        last[0]=now
        done=d.get("downloaded_bytes") or 0
        total=d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        speed=d.get("speed") or 0
        emit(progress=(f"{done/total:.0%}" if total else f"{done/1048576:.1f} MB")+f" · {speed/1048576:.1f} MB/s")
    opts.update(format=selector,outtmpl=str(work/"media.%(ext)s"),progress_hooks=[progress],
                postprocessor_hooks=[lambda d:emit(progress="正在处理音视频")],continuedl=True,overwrites=False)
    if platform(req["source"]) == "bili" and info.get("formats"):
        # Bilibili's DASH CDN serves these resources with HTTP byte ranges.
        opts["http_chunk_size"] = 1024 * 1024
    if req["choice"]=="audio":
        opts["postprocessors"]=[{"key":"FFmpegExtractAudio","preferredcodec":"best"}]
    emit(progress="正在传输")
    if direct and not req.get("single") and req["choice"]!="audio" and not str(req.get("proxy","")).startswith("socks"):
        direct_transfer(req,info,work)
    else:
        with YoutubeDL(opts) as downloader:
            downloader.process_ie_result(info,download=True)
    files=[p for p in work.glob("media.*") if re.fullmatch(r"media\.[\w]+",p.name) and p.suffix not in (".part",".ytdl",".aria2",".temp") and p.stat().st_size]
    if len(files)!=1:
        raise ValueError("成品文件不完整，请重试")
    media=files[0]
    if req["kind"]=="image":
        from PIL import Image
        with Image.open(media) as im:
            im.verify()
        spec={"image":True}
    else:
        spec=probe(media)
        if req["choice"]=="audio" and not spec["audio"]:
            raise ValueError("来源没有音轨")
    target=dest/(safe_name(info.get("title") or req["name"])+" ["+req["id"][:8]+"]"+media.suffix)
    result={"path":str(target),"bytes":media.stat().st_size,"spec":spec}
    receipt.write_text(json.dumps(result,ensure_ascii=True),"utf8")
    media.rename(target)
    emit(done=result)

if __name__=="__main__":
    try:
        private_job()
        run(json.loads(sys.stdin.buffer.readline(4*1024*1024)))
    except Exception as exc:
        emit(error=error_text(exc))
        sys.exit(1)

