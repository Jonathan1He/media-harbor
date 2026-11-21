"""Install a fresh parser beside the active parser. Switch only after an import check."""
import os
import subprocess
import sys
import time
from core import DATA, PYTHON, VENDOR

def switch(value):
    temp=DATA/("engine-"+str(os.getpid())+".tmp")
    temp.write_text(value,encoding="ascii")
    temp.replace(DATA/"engine-current")

def main():
    DATA.mkdir(parents=True,exist_ok=True)
    marker=DATA/"engine-current"
    previous=DATA/"engine-previous"
    if "--rollback" in sys.argv:
        if not previous.exists():raise SystemExit("没有上一版解析器")
        current=marker.read_text() if marker.exists() else ""
        switch(previous.read_text());previous.write_text(current);return
    slot="engine-"+str(time.time_ns())
    dest=DATA/slot
    subprocess.run([str(PYTHON),"-m","pip","install","--disable-pip-version-check","--only-binary=:all:","--index-url","https://pypi.org/simple","--target",str(dest),"yt-dlp[default]"],check=True)
    env=dict(os.environ,PYTHONPATH=str(dest))
    subprocess.run([str(PYTHON),"-c","from yt_dlp import YoutubeDL; import yt_dlp_ejs; YoutubeDL({'quiet':True})"],env=env,check=True)
    previous.write_text(marker.read_text() if marker.exists() else "")
    switch(slot)

if __name__=="__main__":main()

