"""The Windows download manager's widgets and visual styles."""
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk


PAPER = "#ffffff"
INK = "#173439"
MUTED = "#4e696d"
TEAL = "#116b65"
RAIL = "#173d40"
RAIL_ACTIVE = "#2e5658"
LINE = "#d4dfe0"
FONT = "Microsoft YaHei UI"
FILTERS = {
    "all": "全部任务", "active": "传输中", "paused": "已暂停", "done": "已完成",
    "attention": "需处理", "video": "视频", "audio": "音频", "image": "图片",
}


def icon(master, name, color, size):
    # Draw at 4x so strokes and joins stay smooth at Windows display scaling.
    im = Image.new("RGBA", (96, 96))
    draw = ImageDraw.Draw(im)

    def stroke(*coords):
        draw.line([int(c * 4) for c in coords], fill=color, width=7, joint="curve")

    if name == "add":
        stroke(12, 4, 12, 20)
        stroke(4, 12, 20, 12)
    elif name == "play":
        stroke(7, 4, 20, 12, 7, 20, 7, 4)
    elif name == "pause":
        stroke(8, 5, 8, 19)
        stroke(16, 5, 16, 19)
    elif name == "stop":
        stroke(5, 5, 19, 5, 19, 19, 5, 19, 5, 5)
    elif name == "folder":
        stroke(2, 7, 2, 5, 9, 5, 12, 8, 21, 8, 21, 19, 2, 19, 2, 7)
    elif name == "settings":
        for y, x in ((6, 9), (12, 16), (18, 7)):
            stroke(3, y, 21, y)
            draw.ellipse(((x-2)*4, (y-2)*4, (x+2)*4, (y+2)*4), fill=color)
    elif name == "harbor":
        stroke(11, 2, 11, 14, 6, 9)
        stroke(11, 14, 16, 9)
        stroke(2, 14, 5, 20, 18, 20, 22, 12)
    return ImageTk.PhotoImage(im.resize((size, size), Image.Resampling.LANCZOS), master=master)


def configure_style(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=(FONT, 10), background=PAPER, foreground=INK)
    style.configure("TButton", padding=(9, 5), background=PAPER, bordercolor=LINE,
                    lightcolor=PAPER, darkcolor=PAPER)
    style.map("TButton", background=[("active", "#eaf3f2")], foreground=[("disabled", "#849698")])
    style.configure("Accent.TButton", background=TEAL, foreground="white", bordercolor=TEAL,
                    lightcolor=TEAL, darkcolor=TEAL)
    style.map("Accent.TButton", background=[("active", "#0b5a56")], foreground=[("active", "white")])
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("Panel.TLabelframe", bordercolor=LINE)
    style.configure("Panel.TLabelframe.Label", foreground=TEAL, font=(FONT, 10, "bold"))
    style.configure("Treeview", rowheight=max(30, round(root.winfo_fpixels("23p"))),
                    fieldbackground=PAPER, borderwidth=0)
    style.map("Treeview", background=[("selected", "#d3ebe6")], foreground=[("selected", "#083d39")])
    style.configure("Treeview.Heading", background="#edf3f2", foreground=MUTED,
                    font=(FONT, 9, "bold"), padding=(6, 6), relief="flat")


def build_window(app):
    root = app.root
    configure_style(root)
    root.configure(background=PAPER)
    shell = ttk.Frame(root)
    shell.pack(fill="both", expand=True)
    size = max(14, round(root.winfo_fpixels("12p")))
    app.icons = {name: icon(root, name, "white" if name == "add" else TEAL, size)
                 for name in ("add", "play", "pause", "stop", "folder", "settings")}
    app.icons["harbor"] = icon(root, "harbor", "#81ded1", size*2)
    app.rail = tk.Frame(shell, bg=RAIL)
    app.rail.pack(side="left", fill="y")
    tk.Label(app.rail, text="拾流", image=app.icons["harbor"], compound="left", padx=10,
             bg=RAIL, fg="white", font=(FONT, 20, "bold")).pack(anchor="w", padx=12, pady=(20, 18))
    app.nav_buttons = {}
    for group, keys in (("任务", ("all", "active", "paused", "done", "attention")),
                        ("文件类型", ("video", "audio", "image"))):
        tk.Label(app.rail, text=group, bg=RAIL, fg="#a6c6c4", font=(FONT, 9),
                 anchor="w").pack(fill="x", padx=24, pady=(12, 3))
        for key in keys:
            btn = tk.Button(app.rail, text=FILTERS[key], anchor="w", width=13, font=(FONT, 10),
                            bg=RAIL, fg="#e7f2f1", activebackground=RAIL_ACTIVE, activeforeground="white",
                            relief="flat", overrelief="flat", bd=0, highlightthickness=1, highlightbackground=RAIL,
                            highlightcolor="#84d6c8", padx=12, pady=3,
                            command=lambda k=key: app.set_filter(k))
            btn.pack(fill="x", padx=12, pady=1)
            app.nav_buttons[key] = btn

    app.main = ttk.Frame(shell, padding=(16, 12, 16, 10))
    app.main.pack(side="left", fill="both", expand=True)
    head = ttk.Frame(app.main)
    head.pack(fill="x")
    app.heading = tk.StringVar()
    app.head_label = ttk.Label(head, textvariable=app.heading, font=(FONT, 18, "bold"))
    app.head_label.pack(side="left")
    app.compact_nav = ttk.Combobox(head, values=tuple(FILTERS.values()), state="readonly", width=12)
    app.compact_nav.bind("<<ComboboxSelected>>", lambda _: app.set_filter(list(FILTERS)[app.compact_nav.current()]))
    ttk.Button(head, text="设置", image=app.icons["settings"], compound="left",
               command=app.settings).pack(side="right")

    tools = ttk.Frame(app.main)
    tools.pack(fill="x", pady=(10, 9))
    toolbar = (("add", "添加链接", app.open_composer), ("play", "继续 / 重试", lambda: app.change("queued")),
               ("pause", "暂停", lambda: app.change("paused")), ("stop", "取消任务", lambda: app.change("cancelled")),
               ("folder", "打开文件夹", app.folder))
    app.tools = {}
    for key, label, command in toolbar:
        btn = ttk.Button(tools, text=label, image=app.icons[key], compound="left", command=command,
                         style="Accent.TButton" if key == "add" else "TButton", width=0)
        btn.pack(side="left", padx=(0, 6))
        app.tools[key] = btn

    app.forms = ttk.Frame(app.main)
    app.forms.pack(fill="x")
    app.composer = ttk.LabelFrame(app.forms, text="添加链接", padding=(10, 6), style="Panel.TLabelframe")
    entry = ttk.Frame(app.composer)
    entry.pack(fill="x")
    app.link = tk.StringVar()
    app.field = ttk.Entry(entry, textvariable=app.link, width=20)
    app.field.pack(side="left", fill="x", expand=True, ipady=3)
    app.field.bind("<Return>", lambda _: app.inspect())
    ttk.Button(entry, text="解析链接", command=app.inspect).pack(side="left", padx=5)
    ttk.Button(entry, text="收起", command=app.close_composer).pack(side="left")
    app.details = ttk.Frame(app.composer)
    app.details.pack(fill="x", pady=(5, 0))
    app.cover = ttk.Label(app.details)
    app.cover.pack(side="left")
    inner = ttk.Frame(app.details)
    inner.pack(side="left", fill="x", expand=True, padx=4)
    app.title = tk.StringVar(value="粘贴 B 站、YouTube 或媒体链接")
    ttk.Label(inner, textvariable=app.title, wraplength=460).pack(anchor="w")
    row = ttk.Frame(inner)
    row.pack(fill="x", pady=(4, 0))
    app.quality = ttk.Combobox(row, width=18, state="readonly")
    app.quality.pack(side="left")
    app.save_btn = ttk.Button(row, text="保存视频", command=app.save, state="disabled")
    app.save_btn.pack(side="left", padx=5)
    app.audio_btn = ttk.Button(row, text="仅音频", command=lambda: app.save(True), state="disabled")
    app.audio_btn.pack(side="left")
    app.link.trace_add("write", lambda *_: app.invalidate())

    app.save_panel = ttk.LabelFrame(app.forms, text="确认下载", padding=(10, 8), style="Panel.TLabelframe")
    app.pending_name = ttk.Label(app.save_panel, wraplength=490, font=(FONT, 10, "bold"))
    app.pending_name.pack(anchor="w")
    destination = ttk.Frame(app.save_panel)
    destination.pack(fill="x", pady=(6, 0))
    ttk.Label(destination, text="保存到").pack(side="left")
    app.save_to = tk.StringVar()
    app.path_box = ttk.Combobox(destination, textvariable=app.save_to, state="readonly", width=12)
    app.path_box.pack(side="left", expand=True, fill="x", padx=6)
    ttk.Button(destination, text="选择文件夹", command=app.choose_destination).pack(side="left")
    ttk.Button(destination, text="开始下载", style="Accent.TButton", command=app.confirm_save).pack(side="left", padx=4)
    ttk.Button(destination, text="取消", command=app.dismiss_save).pack(side="left")

    table = ttk.Frame(app.main)
    table.pack(fill="both", expand=True)
    table.columnconfigure(0, weight=1)
    table.rowconfigure(0, weight=1)
    app.tree = ttk.Treeview(table, columns=("name", "state", "progress", "dest"), show="headings",
                            selectmode="browse", height=4)
    for col, label, width, minimum in (("name","文件名",255,140), ("state","状态",80,62),
                                       ("progress","进度 / 成品信息",194,115), ("dest","保存位置",188,100)):
        app.tree.heading(col, text=label, anchor="w")
        app.tree.column(col, width=width, minwidth=minimum, stretch=col != "state", anchor="w")
    scroll = ttk.Scrollbar(table, orient="vertical", command=app.tree.yview)
    app.tree.configure(yscrollcommand=scroll.set)
    app.tree.grid(row=0, column=0, sticky="nsew")
    scroll.grid(row=0, column=1, sticky="ns")
    app.tree.bind("<Double-1>", lambda event: app.folder() if app.tree.identify_row(event.y) else None)
    app.tree.bind("<Return>", lambda _: app.folder())
    app.tree.bind("<<TreeviewSelect>>", lambda _: app.show_error())
    app.task_menu = tk.Menu(root, tearoff=False)
    for key in ("play", "pause", "stop", "folder"):
        button = app.tools[key]
        if key == "folder":
            app.task_menu.add_separator()
        app.task_menu.add_command(label=button.cget("text"), command=button.invoke)
    app.tree.bind("<Button-3>", app.open_task_menu)
    app.tree.bind("<Shift-F10>", app.open_task_menu)
    app.empty = ttk.Label(app.tree, style="Muted.TLabel", justify="center")
    ttk.Separator(app.main).pack(fill="x")
    app.summary = tk.StringVar()
    ttk.Label(app.main, textvariable=app.summary, style="Muted.TLabel").pack(anchor="w", pady=(5, 0))
    app.notice = tk.StringVar()
    ttk.Label(app.main, textvariable=app.notice, foreground="#983d25", wraplength=610).pack(anchor="w")
    root.bind("<Control-n>", lambda _: app.open_composer())
    root.bind("<Escape>", lambda _: app.escape())
    root.bind("<Configure>", app.resize, add="+")
