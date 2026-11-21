"""Exercise packaged native host, Tk queue and sqlite with a disposable local profile."""
import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

def main():
    ap=argparse.ArgumentParser();ap.add_argument("package",type=Path);ap.add_argument("temp",type=Path);a=ap.parse_args()
    pkg=a.package.resolve();sys.path.insert(0,str(pkg))
    temp=Path(tempfile.mkdtemp(prefix="desktop-",dir=a.temp))
    os.environ["HARBOR_DATA"]=str(temp/"state")
    from core import connect, enqueue, setpref
    db=connect();setpref(db,"dest",str(temp/"downloads"));setpref(db,"proxy","")
    from PIL import Image
    image=temp/"fixture.png";Image.new("RGB",(200,90),"#128780").save(image)
    class Serve(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):self.serve(True)
        def do_HEAD(self):self.serve(False)
        def serve(self,body):
            self.send_response(200);self.send_header("Content-Length",str(image.stat().st_size))
            self.send_header("ETag",'"fixture"');self.send_header("Content-Type","image/png");self.end_headers()
            if body:self.wfile.write(image.read_bytes())
    http=ThreadingHTTPServer(("127.0.0.1",0),Serve);threading.Thread(target=http.serve_forever,daemon=True).start()
    u="http://127.0.0.1:"+str(http.server_port)+"/fixture.png"
    k=enqueue(db,u,u,"image","auto","recovered",temp/"downloads")
    db.execute("UPDATE jobs SET state='running' WHERE id=?",(k,));db.commit();db.close()
    import tkinter as tk
    from desktop import Desktop
    root=tk.Tk();root.withdraw();app=Desktop(root)
    def call(msg):
        data=json.dumps(msg,ensure_ascii=True).encode()
        proc=subprocess.run([str(pkg/"MediaHarbor.exe"),"chrome-extension://fgknhnjdemnejfagelfoihbdbflodjpl/"],
               input=struct.pack("<I",len(data))+data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=25)
        assert proc.returncode==0 and len(proc.stdout)>4,(proc.returncode,proc.stderr[:100])
        n=struct.unpack("<I",proc.stdout[:4])[0];assert len(proc.stdout)==n+4
        return json.loads(proc.stdout[4:])
    events=[]
    def sender():
        try:events.append(call(dict(op="offer",items=[dict(source=u+"?temporary=fixture",page=u,kind="image",choice="auto",name=name) for name in ("one","two")])))
        except BaseException as exc:events.append({"error":str(exc)})
    threading.Thread(target=sender,daemon=True).start()
    try:
        deadline=time.monotonic()+40
        while time.monotonic()<deadline:
            root.update();time.sleep(.02)
            if events and events[0].get("error"):raise AssertionError(events)
            rows=app.db.execute("SELECT * FROM jobs").fetchall()
            if events and app.pending_saves:
                assert events[0]["pending"] and len(rows)==1 and root.state()=="normal"
                assert app.save_panel.winfo_ismapped()
                app.save_to.set(str(temp/"selected"));app.confirm_save()
            if len(rows)==3 and all(r["state"]=="done" for r in rows):break
        assert len(rows)==3 and all(r["state"]=="done" for r in rows),[(r["state"],r["error"]) for r in rows]
        assert all(Path(r["result"]).read_bytes()==image.read_bytes() for r in rows)
        assert all("temporary" not in r["source"] for r in rows)
        assert all(Path(r["result"]).parent==temp/"selected" for r in rows if r["id"]!=k)
        item=dict(source=u,page=u,kind="image",choice="auto",name="cancel")
        assert app.offer([item])["pending"]
        assert Path(app.save_to.get())==temp/"selected"
        assert temp/"downloads" in map(Path,app.path_box.cget("values"))
        app.save_to.set(str(temp/"cancelled-folder"));app.dismiss_save()
        assert not (temp/"cancelled-folder").exists()
        assert Path(app.recent_paths[0])==temp/"selected"
        assert app.db.execute("SELECT count(*) FROM jobs").fetchone()[0]==3
        app.set_filter("image");assert len(app.tree.get_children())==3
        app.set_filter("audio");assert not app.tree.get_children()
        app.tools["add"].invoke();root.update()
        app.link.set(u);assert app.field.get()==u
        app.escape();assert not app.composer.winfo_manager()
        app.tools["add"].invoke();assert app.field.get()==u
        app.close_composer()
        root.geometry("650x420");root.update()
        assert app.compact_nav.winfo_ismapped() and not app.rail.winfo_ismapped()
        app.compact_nav.set("已完成");app.compact_nav.event_generate("<<ComboboxSelected>>");root.update()
        assert len(app.tree.get_children())==3
        root.geometry("1020x610");root.update()
        assert app.rail.winfo_ismapped() and app.filter_key=="done"
        setpref(app.db,"confirm_dest","0")
        assert not app.offer([item])["pending"]
        assert app.db.execute("SELECT dest FROM jobs WHERE name='cancel'").fetchone()[0]==str(temp/"downloads")
        code=("import sys,tkinter as tk;sys.path.insert(0,sys.argv[1]);import desktop;"
              "desktop.bridge.serve=lambda dispatch:None;root=tk.Tk();root.withdraw();app=desktop.Desktop(root);"
              "app.pending_saves.append([{'name':'restart'}]);app.show_pending();"
              "assert app.save_to.get()==sys.argv[2];app.close()")
        subprocess.run([sys.executable,"-B","-c",code,str(pkg),str(temp/"selected")],check=True,timeout=15)
        print("PASS: browser/native offer, batch destination, history after restart, cancel, default path, filters, compact layout and worker integrity",flush=True)
    finally:app.close();http.shutdown();http.server_close()
if __name__=="__main__":main()

