import ctypes
import json
import os
import queue
import shutil
import subprocess
import threading
import time
import tkinter as tk
from collections import deque
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from urllib.parse import urlsplit
import bridge
from desktop_ui import FILTERS, RAIL, RAIL_ACTIVE, build_window
from core import DATA, HIDE, PIPE, PYTHON, ROOT, connect, durable, enqueue, error_text, platform, preference, setpref, url, validate_tracks

STATES={"queued":"等待","running":"下载中","paused":"已暂停","done":"已完成","error":"失败","cancelled":"已取消","refresh":"需重选资源"}

def worker(req):
    p=subprocess.Popen([str(PYTHON),"-B",str(ROOT/"engine.py")],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL,creationflags=HIDE)
    p.stdin.write((json.dumps(req,ensure_ascii=True)+"\n").encode())
    p.stdin.close()
    return p

def inspect_media(req):
    p=worker(dict(req,action="inspect"))
    try:
        import threading
        timer=threading.Timer(120,p.kill)
        timer.start()
        events=[json.loads(line) for line in p.stdout]
        p.wait()
    finally:
        timer.cancel()
        p.stdout.close()
    for e in events:
        if "info" in e: return e["info"]
        if e.get("error"): raise ValueError(e["error"])
    raise ValueError("解析进程已结束或超时，请检查网络和代理")

def classify(source):
    ext=Path(urlsplit(source).path).suffix.lower()
    for kind,exts in (("image",(".jpg",".jpeg",".png",".gif",".webp",".bmp",".avif")),
                      ("video",(".mp4",".mkv",".webm",".mov")),("audio",(".mp3",".m4a",".flac",".ogg",".wav"))):
        if ext in exts: return kind
    return "page"

def request(raw):
    s=url(raw["source"])
    p=url(raw.get("page") or s)
    kind=raw.get("kind") or classify(s)
    choice=str(raw.get("choice") or "auto")
    if kind not in ("video","audio","stream","image","page") or len(choice)>100:
        raise ValueError("无效的下载选项")
    r=dict(source=s,page=p,kind=kind,choice=choice,name=str(raw.get("name") or Path(urlsplit(s).path).name or "媒体")[:180],
           mime=str(raw.get("mime",""))[:100])
    if raw.get("tracks"):
        if durable(s)!=durable(p) or not platform(p):
            raise ValueError("请在当前平台播放页重试")
        r.update(tracks=validate_tracks(p,raw["tracks"]),media_id=durable(p))
    return r

def discard_staging(row):
    stage=Path(row["dest"])/(".media-harbor-"+row["id"])
    if not stage.is_dir() or stage.is_symlink() or stage.is_junction():return
    if stage.resolve().parent==Path(row["dest"]).resolve():
        try:shutil.rmtree(stage)
        except OSError:pass

class Desktop:
    def __init__(self,root):
        self.root=root
        self.db=connect()
        self.events=queue.Queue()
        self.live={}
        self.procs={}
        self.last_render=0
        self.generation=0
        self.resolved=None
        self.pending_saves=deque()
        self.closing=False
        with self.db:
            self.db.execute("UPDATE jobs SET state=CASE WHEN volatile=1 THEN 'refresh' ELSE 'queued' END WHERE state IN ('running','queued')")
        root.title("拾流 · Media Harbor")
        root.geometry("1020x610")
        root.minsize(650,420)
        self.recent_paths = self.load_recent_paths()
        self.restore_composer = False
        self.compact = None
        build_window(self)
        self.set_filter("all")
        threading.Thread(target=bridge.serve,args=(self.call,),daemon=True).start()
        root.after(100,self.tick)
        root.protocol("WM_DELETE_WINDOW",self.close)

    def open_composer(self):
        if self.pending_saves:
            self.path_box.focus_set()
            return
        self.composer.pack(fill="x", pady=(0, 8))
        self.field.focus_set()
        self.field.selection_range(0, "end")

    def close_composer(self):
        self.composer.pack_forget()
        self.tools["add"].focus_set()

    def escape(self):
        if self.pending_saves:
            self.dismiss_save()
        elif self.composer.winfo_manager():
            self.close_composer()

    def set_filter(self, key):
        self.filter_key = key
        self.heading.set(FILTERS[key])
        self.compact_nav.set(FILTERS[key])
        for name, button in self.nav_buttons.items():
            button.configure(bg=RAIL_ACTIVE if name == key else RAIL)
        self.notice.set("")
        self.render()

    def resize(self, event):
        if event.widget is not self.root:
            return
        compact = event.width < 835 or event.height < max(510, self.rail.winfo_reqheight() + 8)
        if compact == self.compact:
            return
        self.compact = compact
        if compact:
            self.rail.pack_forget()
            self.head_label.pack_forget()
            self.compact_nav.pack(side="left")
        else:
            self.rail.pack(side="left", fill="y", before=self.main)
            self.compact_nav.pack_forget()
            self.head_label.pack(side="left")
        self.tree.configure(displaycolumns=("name", "state", "progress") if compact else "#all")

    def load_recent_paths(self):
        stored = preference(self.db, "recent_destinations", "")
        if stored:
            try:
                paths = json.loads(stored)
                if isinstance(paths, list):
                    return self.unique_paths(paths)
            except ValueError:
                pass
        rows = self.db.execute("""SELECT dest FROM jobs WHERE dest <> ''
            GROUP BY dest COLLATE NOCASE ORDER BY MAX(created) DESC LIMIT 32""")
        return self.unique_paths(row[0] for row in rows)

    @staticmethod
    def unique_paths(paths):
        recent = []
        seen = set()
        for path in paths:
            if not isinstance(path, str) or not os.path.isabs(path):
                continue
            normal = os.path.normpath(path)
            key = os.path.normcase(normal)
            if key not in seen:
                seen.add(key)
                recent.append(normal)
        return recent[:8]

    def remember_path(self, path):
        self.recent_paths = self.unique_paths([str(path), *self.recent_paths])
        setpref(self.db, "recent_destinations", json.dumps(self.recent_paths, ensure_ascii=False))

    def dest(self):
        return preference(self.db,"dest",str(Path.home()/"Downloads"/"拾流"))

    def show_window(self):
        if self.root.state() in ("withdrawn","iconic"):
            self.root.deiconify()
        self.root.lift()
        if not self.root.attributes("-topmost"):
            self.root.attributes("-topmost",True)
            self.root.after(200,lambda:self.root.attributes("-topmost",False))
        self.root.focus_force()

    def offer(self,items):
        self.show_window()
        if preference(self.db,"confirm_dest","1")=="0":
            for item in items:
                self.add(item,self.dest())
            return {"ok":True,"pending":False}
        self.pending_saves.append(items)
        if len(self.pending_saves)==1:
            self.restore_composer = bool(self.composer.winfo_manager())
            self.composer.pack_forget()
            self.show_pending()
        return {"ok":True,"pending":True}

    def show_pending(self):
        items=self.pending_saves[0]
        title=items[0]["name"] if len(items)==1 else f"{len(items)} 个文件 · {items[0]['name']} 等"
        self.pending_name.configure(text=title)
        choices = list(self.recent_paths)
        default = os.path.normpath(self.dest())
        if os.path.normcase(default) not in {os.path.normcase(p) for p in choices}:
            choices.append(default)
        self.path_box.configure(values=choices)
        self.save_to.set(choices[0])
        self.save_panel.pack(fill="x", pady=(0, 8))
        self.path_box.focus_set()

    def choose_destination(self):
        folder=Path(self.save_to.get())
        chosen=filedialog.askdirectory(parent=self.root,title="选择本次下载的保存文件夹",
            initialdir=str(folder if folder.is_dir() else folder.parent))
        if chosen:self.save_to.set(chosen)

    def confirm_save(self):
        if not self.pending_saves:return
        items=self.pending_saves[0]
        try:
            dest=Path(self.save_to.get())
            dest.mkdir(parents=True,exist_ok=True)
            while items:
                self.add(items[0],dest)
                items.pop(0)
            self.remember_path(dest)
        except (OSError,ValueError) as exc:
            self.notice.set(error_text(exc))
            return
        self.dismiss_save()

    def dismiss_save(self):
        if not self.pending_saves:return
        self.pending_saves.popleft()
        if self.pending_saves:self.show_pending()
        else:
            self.save_panel.pack_forget()
            if self.restore_composer:
                self.open_composer()
            else:
                self.tree.focus_set()

    def invalidate(self):
        self.generation+=1;self.resolved=None
        self.quality.set("");self.quality["values"]=()
        self.cover.configure(image="");self.cover.image=None
        self.save_btn.configure(state="disabled");self.audio_btn.configure(state="disabled")

    def inspect(self):
        try: req=request({"source":self.link.get()})
        except Exception as e: self.notice.set(str(e));return
        self.invalidate();gen=self.generation
        self.title.set("正在读取可用画质…");self.notice.set("")
        req["proxy"]=preference(self.db,"proxy","system")
        def work():
            try:
                info=inspect_media(req)
                self.events.put(("resolved",gen,req,info))
                if info.get("thumbnail"):
                    from io import BytesIO
                    from PIL import Image
                    import urllib.request as ur
                    px=req["proxy"]
                    handler=ur.ProxyHandler(None if px=="system" else {k:px for k in ("http","https")})
                    with ur.build_opener(handler).open(url(info["thumbnail"]),timeout=8) as response:
                        blob=response.read(2_000_001)
                    if len(blob)<=2_000_000:
                        with Image.open(BytesIO(blob)) as im:
                            im.thumbnail((114,70)); self.events.put(("cover",gen,im.copy()))
            except Exception as e:
                self.events.put(("inspect_error",gen,error_text(e)))
        threading.Thread(target=work,daemon=True).start()

    def save(self,audio=False):
        if not self.resolved:return
        req,info=self.resolved
        idx=self.quality.current()
        choice="audio" if audio else ("id:"+str(info["choices"][idx-1]["id"]) if idx>0 else "auto")
        try:self.offer([dict(req,choice=choice,name=info["title"])])
        except Exception as e:self.notice.set(error_text(e))

    def add(self,r,dest=None):
        key=enqueue(self.db,r["source"],r["page"],r["kind"],r["choice"],r["name"],dest or self.dest(),bool(r.get("tracks")))
        self.live[key]=r
        self.last_render=0
        return key

    def call(self,msg):
        reply=queue.Queue(1)
        self.events.put(("ipc",msg,reply))
        try:return reply.get(timeout=145)
        except queue.Empty:return {"error":"桌面程序繁忙"}

    def ipc(self,msg,reply):
        try:
            op=msg.get("op")
            if op=="open":
                self.show_window();reply.put({"ok":True});return
            if op=="offer":
                batch=msg.get("items")
                if not isinstance(batch,list) or not 1<=len(batch)<=350:
                    raise ValueError("请选择至少一个资源，单次最多 350 个")
                reply.put(self.offer([request(item) for item in batch]))
                return
            r=request(msg)
            r["proxy"]=preference(self.db,"proxy","system")
            if op=="inspect":
                def resolve():
                    try:reply.put({"info":inspect_media(r)})
                    except Exception as e:reply.put({"error":error_text(e)})
                threading.Thread(target=resolve,daemon=True).start();return
            if op!="enqueue":raise ValueError("不支持的操作")
            self.show_window()
            reply.put({"ok":True,"id":self.add(r)})
        except Exception as e:reply.put({"error":error_text(e)})

    def start(self,row):
        k=row["id"]
        r=self.live.get(k)
        if r is None and row["volatile"]:
            with self.db:self.db.execute("UPDATE jobs SET state='refresh',error='请在原网页重新选择该资源。' WHERE id=?",(k,))
            return
        req=dict(r or {v:row[v] for v in ("source","page","kind","choice","name")},action="download",id=k,dest=row["dest"],proxy=preference(self.db,"proxy","system"))
        with self.db:self.db.execute("UPDATE jobs SET state='running',progress='正在解析',error='' WHERE id=?",(k,))
        try:p=worker(req)
        except OSError as e:
            with self.db:self.db.execute("UPDATE jobs SET state='error',error=? WHERE id=?",(error_text(e),k))
            return
        self.procs[k]=p
        def listen():
            try:
                for line in p.stdout:self.events.put(("worker",k,p,json.loads(line)))
            finally:
                p.stdout.close();p.wait();self.events.put(("exit",k,p))
        threading.Thread(target=listen,daemon=True).start()

    def update_job(self,k,e):
        with self.db:
            if e.get("done"):
                d=e["done"];spec=d["spec"]
                desc=(f"{spec['height']}p · {spec['fps']:g} fps" if spec.get("height") else ("图片" if spec.get("image") else "音频"))
                self.db.execute("UPDATE jobs SET state='done',result=?,progress=?,name=? WHERE id=?",(d["path"],desc+" · "+f"{d['bytes']/1048576:.1f} MB",Path(d["path"]).name,k))
                self.live.pop(k,None)
            elif e.get("error"):
                self.db.execute("UPDATE jobs SET state='error',error=?,progress='' WHERE id=?",(e["error"],k))
            elif e.get("progress"):
                self.db.execute("UPDATE jobs SET progress=? WHERE id=?",(e["progress"],k))
        if e.get("done"):
            discard_staging(self.db.execute("SELECT id,dest FROM jobs WHERE id=?",(k,)).fetchone())

    def tick(self):
        try:
            for _ in range(100):
                try:typ,*a=self.events.get_nowait()
                except queue.Empty:break
                if typ=="ipc":self.ipc(*a)
                elif typ=="notice":self.notice.set(a[0])
                elif typ=="worker" and self.procs.get(a[0]) is a[1]:self.update_job(a[0],a[2])
                elif typ=="exit" and self.procs.get(a[0]) is a[1]:
                    self.procs.pop(a[0])
                    with self.db:self.db.execute("UPDATE jobs SET state='error',error='下载进程意外结束' WHERE id=? AND state='running'",(a[0],))
                elif typ=="resolved" and a[0]==self.generation:
                    req,info=a[1:];self.resolved=req,info
                    self.title.set(info["title"])
                    self.quality["values"]=["自动 · "+info["default"]]+[c["label"] for c in info["choices"]]
                    self.quality.current(0)
                    self.save_btn.configure(state="normal",text="保存文件" if req["kind"] in ("image","audio") else "保存视频")
                    self.audio_btn.configure(state="disabled" if req["kind"]=="image" else "normal")
                elif typ=="cover" and a[0]==self.generation:
                    from PIL import ImageTk
                    self.cover.image=ImageTk.PhotoImage(a[1]);self.cover.configure(image=self.cover.image)
                elif typ=="inspect_error" and a[0]==self.generation and not self.resolved:
                    self.title.set("解析失败");self.notice.set(a[1])
            if len(self.procs)<2:
                row=self.db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
                if row:self.start(row)
            if time.monotonic()-self.last_render>.5:self.render()
        finally:
            if not self.closing:self.root.after(125,self.tick)

    def render(self):
        visible = []
        total = active = 0
        for row in self.db.execute("SELECT * FROM jobs ORDER BY created DESC, id"):
            total += 1
            state = row["state"]
            group = {"running":"active", "queued":"active", "error":"attention", "refresh":"attention"}.get(state, state)
            active += group == "active"
            kind = row["kind"]
            media = kind if kind in ("audio", "image") else "video"
            if row["choice"] == "audio":
                media = "audio"
            if self.filter_key in ("all", group, media):
                visible.append(row)
        keep = {r["id"] for r in visible}
        for key in self.tree.get_children():
            if key not in keep:
                self.tree.delete(key)
        for index, row in enumerate(visible):
            key = row["id"]
            values = (row["name"], STATES.get(row["state"],row["state"]), row["error"] or row["progress"], row["dest"])
            if self.tree.exists(key):
                self.tree.item(key, values=values)
            else:
                self.tree.insert("", index, iid=key, values=values)
        if visible:
            self.empty.place_forget()
        else:
            self.empty.configure(text="还没有下载任务\n点击「添加链接」，或从浏览器开始下载。" if not total else "此分类下暂无任务")
            self.empty.place(relx=0.5, rely=0.54, anchor="center")
        self.summary.set(f"当前显示 {len(visible)} 项    /    共 {total} 项     ·     传输中 {active} 项")
        self.update_actions()
        self.last_render=time.monotonic()

    def selected(self):
        keys=self.tree.selection()
        return self.db.execute("SELECT * FROM jobs WHERE id=?",keys).fetchone() if keys else None

    def show_error(self):
        row=self.selected()
        if row:self.notice.set(row["error"])
        self.update_actions()

    def update_actions(self):
        row = self.selected()
        state = row["state"] if row else None
        allowed = {"play":state in ("paused","error"), "pause":state in ("running","queued"),
                   "stop":bool(row) and state not in ("done","cancelled")}
        for name, enabled in allowed.items():
            self.tools[name].state(["!disabled" if enabled else "disabled"])

    def open_task_menu(self, event):
        if event.num == 3:
            key = self.tree.identify_row(event.y)
            if not key:
                return
            self.tree.selection_set(key)
            x, y = event.x_root, event.y_root
        else:
            row = self.selected()
            if not row:
                return
            self.tree.see(row["id"])
            left, top, _, height = self.tree.bbox(row["id"])
            x, y = self.tree.winfo_rootx() + left + 16, self.tree.winfo_rooty() + top + height
        self.update_actions()
        for key in ("play", "pause", "stop"):
            button = self.tools[key]
            self.task_menu.entryconfigure(button.cget("text"), state="disabled" if button.instate(["disabled"]) else "normal")
        try:
            self.task_menu.tk_popup(x, y)
        finally:
            self.task_menu.grab_release()
        return "break"

    def change(self,state):
        row=self.selected()
        if not row or row["state"] in ("done","cancelled"):return
        k=row["id"]
        if state=="queued" and row["state"]=="running":return
        p=self.procs.pop(k,None)
        if p:p.kill();p.wait()
        if state=="cancelled":
            self.live.pop(k,None);discard_staging(row)
        with self.db:self.db.execute("UPDATE jobs SET state=?,progress='',error='' WHERE id=?",(state,k))
        self.render()

    def folder(self):
        row=self.selected()
        if row and row["result"] and Path(row["result"]).exists():
            subprocess.Popen(["explorer.exe","/select,",row["result"]]);return
        d=Path(row["dest"] if row else self.dest())
        try:
            d.mkdir(parents=True,exist_ok=True)
            os.startfile(d)
        except OSError as exc:
            self.notice.set(error_text(exc))

    def settings(self):
        win=tk.Toplevel(self.root);win.title("下载设置");win.transient(self.root)
        frm=ttk.Frame(win,padding=18);frm.pack(fill="both",expand=True)
        dest=tk.StringVar(value=self.dest());proxy=tk.StringVar(value=preference(self.db,"proxy","system"))
        confirm=tk.BooleanVar(value=preference(self.db,"confirm_dest","1")=="1")
        ttk.Label(frm,text="默认保存位置").grid(row=0,column=0,sticky="w")
        ttk.Combobox(frm,textvariable=dest,values=list(dict.fromkeys([self.dest(), *self.recent_paths])),
                     width=45,state="readonly").grid(row=1,column=0,pady=4)
        ttk.Button(frm,text="选择",command=lambda:dest.set(filedialog.askdirectory(parent=win) or dest.get())).grid(row=1,column=1)
        ttk.Label(frm,text="代理（system 跟随系统，留空直连，或填写代理地址）").grid(row=2,column=0,columnspan=2,sticky="w",pady=(8,1))
        ttk.Entry(frm,textvariable=proxy,width=45).grid(row=3,column=0,columnspan=2,sticky="ew")
        ttk.Checkbutton(frm,text="下载前确认保存位置",variable=confirm).grid(row=4,column=0,sticky="w")
        def save():
            value=proxy.get().strip()
            if value not in ("","system"):
                q=urlsplit(value)
                if q.scheme not in ("http","https","socks5","socks5h") or not q.hostname or q.username or q.password:
                    messagebox.showerror("代理","请输入无账号密码的代理地址",parent=win);return
            if os.path.normcase(os.path.normpath(dest.get())) != os.path.normcase(os.path.normpath(self.dest())):
                self.remember_path(dest.get())
            setpref(self.db,"dest",dest.get());setpref(self.db,"proxy",value)
            setpref(self.db,"confirm_dest","1" if confirm.get() else "0");win.destroy()
        ttk.Button(frm,text="保存",command=save).grid(row=4,column=1,pady=(10,0))
        buttons=ttk.Frame(frm);buttons.grid(row=5,column=0,columnspan=2,sticky="w",pady=(12,0))
        def engine_update(rollback):
            if getattr(self,"updating",False):return
            self.updating=True;win.destroy()
            self.notice.set("正在切换解析器…" if rollback else "正在从 PyPI 更新解析器…")
            def update():
                try:
                    args=[str(PYTHON),str(ROOT/"update_engine.py")]+(["--rollback"] if rollback else [])
                    result=subprocess.run(args,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,creationflags=HIDE,timeout=300)
                    msg="解析器已切换，新任务会使用新版本" if result.returncode==0 else "解析器切换失败，原版本仍可使用"
                except Exception as exc:msg=error_text(exc)
                finally:self.updating=False
                self.events.put(("notice",msg))
            threading.Thread(target=update,daemon=True).start()
        ttk.Button(buttons,text="更新解析器",command=lambda:engine_update(False)).pack(side="left")
        ttk.Button(buttons,text="回退上一版",command=lambda:engine_update(True)).pack(side="left",padx=6)

    def close(self):
        self.closing=True
        for p in self.procs.values():p.kill();p.wait()
        with self.db:self.db.execute("UPDATE jobs SET state='queued' WHERE state='running'")
        self.db.close();self.root.destroy()

if __name__=="__main__":
    ctypes.windll.kernel32.CreateMutexW(None,False,"Local\\MediaHarbor-"+PIPE.rsplit("-",1)[-1])
    if ctypes.windll.kernel32.GetLastError()==183:
        bridge.send({"op":"open"},False)
    else:
        root=tk.Tk();Desktop(root);root.mainloop()

