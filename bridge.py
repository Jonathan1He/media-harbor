"""Native Messaging uses framed JSON, local desktop IPC uses authenticated byte messages."""
import json
import os
import struct
import subprocess
import sys
import threading
import time
from multiprocessing.connection import Client, Listener
from core import DATA, HIDE, PIPE, ROOT

MAX = 900_000
def decode(data):
    if len(data)>MAX:
        raise ValueError("资源清单太大")
    message=json.loads(data)
    if not isinstance(message,dict):
        raise ValueError("无效消息")
    return message

def key():
    return (DATA/"ipc.key").read_bytes()

def serve(dispatch):
    DATA.mkdir(parents=True,exist_ok=True)
    try:
        with (DATA/"ipc.key").open("xb") as f:
            f.write(os.urandom(32))
    except FileExistsError:
        pass
    def client(conn):
        try:
            if not conn.poll(8):
                return
            msg=decode(conn.recv_bytes(MAX))
            result=dispatch(msg)
            conn.send_bytes(json.dumps(result,ensure_ascii=True).encode())
        except (OSError,EOFError,ValueError):
            pass
        finally:
            conn.close()
    with Listener(PIPE,family="AF_PIPE",authkey=key()) as listener:
        while True:
            try:
                conn=listener.accept()
            except (OSError,EOFError):
                continue
            threading.Thread(target=client,args=(conn,),daemon=True).start()

def send(msg,start=True):
    deadline=time.monotonic()+12
    while True:
        try:
            conn=Client(PIPE,family="AF_PIPE",authkey=key())
            break
        except (FileNotFoundError,ConnectionRefusedError):
            if msg.get("op")=="inspect" and msg.get("passive"):
                return {"error":"点击下载即可打开拾流"}
            if start:
                subprocess.Popen([str(sys.executable).replace("python.exe","pythonw.exe"),str(ROOT/"desktop.py")],
                    cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=HIDE)
                start=False
            if time.monotonic()>deadline:
                raise ValueError("桌面程序没有响应，请打开「拾流」再试")
            time.sleep(.15)
    with conn:
        conn.send_bytes(json.dumps(msg,ensure_ascii=True).encode())
        if not conn.poll(150):
            raise ValueError("解析超时，请在桌面端重试")
        return decode(conn.recv_bytes(MAX))

def native():
    data=sys.stdin.buffer
    header=data.read(4)
    if not header:
        return
    try:
        n,=struct.unpack("<I",header)
        if not 0<n<=MAX:
            raise ValueError("请求过大")
        result=send(decode(data.read(n)))
    except Exception as exc:
        result={"error":str(exc)[:200]}
    payload=json.dumps(result,ensure_ascii=True).encode()
    sys.stdout.buffer.write(struct.pack("<I",len(payload))+payload)
    sys.stdout.buffer.flush()

if __name__=="__main__":
    native()

