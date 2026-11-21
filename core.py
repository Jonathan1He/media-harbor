"""Shared validation, durable queue and bundle layout."""
import hashlib
import json
import os
import re
import sqlite3
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("HARBOR_DATA", Path(os.environ["LOCALAPPDATA"]) / "MediaHarbor" / "data"))
TOOLS = Path(os.environ.get("HARBOR_TOOLS", ROOT / "tools"))
VENDOR = Path(os.environ.get("HARBOR_VENDOR", ROOT / "vendor"))
if (DATA / "engine-current").is_file():
    slot = (DATA / "engine-current").read_text().strip()
    if re.fullmatch(r"engine-[a-zA-Z0-9.-]+", slot) and (DATA / slot / "yt_dlp").is_dir():
        sys.path.insert(0, str(DATA / slot))
sys.path.insert(1, str(VENDOR))
os.environ["PATH"] = str(TOOLS) + os.pathsep + os.environ["PATH"]
PYTHON = Path(sys.executable).with_name("python.exe")
HIDE = 0x08000000 if os.name == "nt" else 0
PIPE = r"\\.\pipe\MediaHarbor-" + hashlib.sha256(str(DATA).lower().encode()).hexdigest()[:24]

def url(value):
    if not isinstance(value, str) or len(value) > 16384 or any(ord(c) < 32 for c in value):
        raise ValueError("链接格式无效")
    p = urlsplit(value.strip())
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        raise ValueError("请输入 HTTP 或 HTTPS 链接")
    return value.strip()

def host(value):
    return (urlsplit(value).hostname or "").lower()

def domain(h, suffix):
    return h == suffix or h.endswith("." + suffix)

def platform(value):
    h = host(value)
    if domain(h, "bilibili.com") or h == "b23.tv":
        return "bili"
    if domain(h, "youtube.com") or h == "youtu.be":
        return "youtube"
    return ""

def durable(value):
    p = urlsplit(url(value))
    q = parse_qs(p.query)
    if platform(value):
        keep = {k: q[k][0] for k in ("v", "p") if k in q}
        return urlunsplit((p.scheme, p.netloc, p.path, urlencode(keep), ""))
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))

def safe_name(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name))[:110].strip(" .") or "media"
    return "_" + name if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", name, re.I) else name

def error_text(err):
    s = re.sub(r"\x1b\[[0-9;]*m", "", str(err))
    s = re.sub(r"https?://\S+", "[来源链接]", s).strip()[:420]
    if "HTTP Error 412" in s:
        return "站点拒绝了本次解析请求（HTTP 412）。可在浏览器官网正常播放后，打开拾流扩展，选择「用当前播放器重试」。"
    return s

def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA / "queue.sqlite3", timeout=12)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS jobs(
          id TEXT PRIMARY KEY, source TEXT, page TEXT, kind TEXT, choice TEXT, name TEXT,
          dest TEXT, state TEXT, progress TEXT DEFAULT '', result TEXT DEFAULT '',
          error TEXT DEFAULT '', volatile INTEGER, created REAL, signature TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS prefs(key TEXT PRIMARY KEY, value TEXT);
    """)
    return db

def preference(db, key, default=""):
    row = db.execute("SELECT value FROM prefs WHERE key=?", (key,)).fetchone()
    return row[0] if row else default

def setpref(db, key, value):
    with db:
        db.execute("INSERT OR REPLACE INTO prefs VALUES(?,?)", (key, value))

def enqueue(db, source, page, kind, choice, name, dest, ephemeral=False):
    import time
    source, page = url(source), url(page)
    if kind not in ("page","video","audio","image","stream"):
        raise ValueError("不支持的资源类型")
    clean = durable(source)
    volatile = ephemeral or (not platform(source) and bool(urlsplit(source).query))
    key = uuid.uuid4().hex
    with db:
        if volatile:
            previous=db.execute("""SELECT id FROM jobs WHERE source=? AND page=? AND kind=? AND
                choice=? AND name=? AND dest=? AND state IN ('refresh','error') AND volatile=1 ORDER BY created DESC LIMIT 1""",
                (clean,durable(page),kind,choice,safe_name(name),str(dest))).fetchone()
            if previous:
                db.execute("UPDATE jobs SET state='queued',error='' WHERE id=?",(previous[0],))
                return previous[0]
        db.execute("""INSERT INTO jobs(id,source,page,kind,choice,name,dest,state,volatile,created)
                      VALUES(?,?,?,?,?,?,?,'queued',?,?)""",
                   (key, clean, durable(page), kind, choice, safe_name(name), str(dest), int(volatile), time.time()))
    return key

def validate_tracks(page, tracks):
    """Only player-supplied media for the selected platform; never accept cookies or headers."""
    if not isinstance(tracks,list) or len(tracks)>180 or not platform(page):
        raise ValueError("播放器未提供此格式")
    cdns = ("bilivideo.com","bilivideo.cn","bilibili.com","akamaized.net") if platform(page)=="bili" else ("googlevideo.com",)
    out = []
    for item in tracks:
        u = url(item["url"])
        if urlsplit(u).scheme != "https" or not any(domain(host(u),d) for d in cdns):
            continue
        kind = item.get("kind")
        if kind not in ("video","audio","both"):
            continue
        out.append(dict(url=u,kind=kind,id=safe_name(item.get("id","track")),height=min(16384,max(0,int(item.get("height") or 0))),fps=min(1000,max(0,float(item.get("fps") or 0))),ext="webm" if item.get("ext")=="webm" else ("m4a" if kind=="audio" else "mp4")))
    if not out:
        raise ValueError("当前播放器没有提供可直接保存的媒体地址")
    return out

