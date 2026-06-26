import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import time
import os
import threading
import shutil
from typing import Optional
from tkinterdnd2 import Tk as DnDTk, DND_FILES

from network import NetworkManager, Peer, ChatMessage


def format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    else:
        return f"{size / 1024 / 1024:.1f} MB"


def format_time(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts))


CHAT_PAD = 0
COLOR_SELF_BG = "#dcf8c6"
COLOR_OTHER_BG = "#ffffff"
COLOR_SELF_FG = "#000000"
COLOR_OTHER_FG = "#000000"
COLOR_SYSTEM = "#999999"


class ChatBubbleFrame(tk.Frame):
    RADIUS = 10

    def __init__(self, parent, msg: ChatMessage, on_open_file=None):
        super().__init__(parent)
        self.msg = msg
        self.on_open_file = on_open_file
        bg = parent.cget("bg")
        self.configure(bg=bg)

        bubble_bg = COLOR_SELF_BG if msg.is_self else COLOR_OTHER_BG
        anchor = tk.E if msg.is_self else tk.W
        padx_right = 0 if msg.is_self else 40
        padx_left = 40 if msg.is_self else 0

        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        content = tk.Frame(self.canvas, bg=bubble_bg)

        tk.Label(
            content, text=format_time(msg.timestamp),
            fg=COLOR_SYSTEM, bg=bubble_bg,
            font=("Segoe UI", 8), anchor=tk.E,
        ).pack(fill=tk.X, padx=12, pady=(4, 0))

        if msg.is_file:
            self._build_file_widget(content, bubble_bg)
        else:
            self._build_text_widget(content, bubble_bg)

        self.canvas.pack()
        win_id = self.canvas.create_window(0, 0, anchor=tk.NW, window=content)
        self.canvas.update_idletasks()
        cw = content.winfo_width()
        ch = content.winfo_height()
        if cw <= 1:
            cw = content.winfo_reqwidth()
            ch = content.winfo_reqheight()
        self.canvas.delete(win_id)
        self.canvas.pack_forget()

        extra = self.RADIUS
        self.canvas.configure(width=cw + extra, height=ch + 4)
        self.canvas.pack(anchor=anchor, pady=2, padx=(padx_left, padx_right))
        self._round_rect(self.canvas, 0, 0, cw + extra - 1, ch + 3,
                         self.RADIUS, fill=bubble_bg, outline="")
        self.canvas.create_window((cw + extra) // 2, (ch + 4) // 2,
                                  window=content)
        self.canvas.bind("<Button-3>", self._show_context_menu)

    @staticmethod
    def _round_rect(c, x1, y1, x2, y2, r=10, **kwargs):
        r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
        points = [
            x1 + r, y1, x2 - r, y1,
            x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2,
            x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r,
            x1, y1 + r, x1, y1,
        ]
        return c.create_polygon(points, smooth=True, **kwargs)

    def _build_text_widget(self, parent, bubble_bg):
        lbl = tk.Label(
            parent, text=self.msg.content,
            bg=bubble_bg,
            fg=COLOR_SELF_FG if self.msg.is_self else COLOR_OTHER_FG,
            font=("Segoe UI", 10), wraplength=400,
            justify=tk.LEFT, anchor=tk.W,
        )
        lbl.pack(fill=tk.X, padx=12, pady=(0, 4))
        lbl.bind("<Button-3>", self._show_context_menu)

    def _build_file_widget(self, parent, bubble_bg):
        inner = tk.Frame(parent, bg=bubble_bg)
        inner.pack(fill=tk.X, padx=12, pady=(0, 4))

        icon_lbl = tk.Label(inner, text="📎", font=("Segoe UI", 16), bg=bubble_bg)
        icon_lbl.pack(side=tk.LEFT, padx=(0, 6))

        info_frame = tk.Frame(inner, bg=bubble_bg)
        info_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        name_lbl = tk.Label(
            info_frame, text=self.msg.file_name,
            font=("Segoe UI", 10, "bold"), fg="#1565C0",
            bg=bubble_bg, cursor="hand2",
            wraplength=300, anchor=tk.W,
        )
        name_lbl.pack(fill=tk.X)
        name_lbl.bind("<Button-1>", lambda e: self._open_file())

        size_lbl = tk.Label(
            info_frame, text=format_size(self.msg.file_size),
            font=("Segoe UI", 8), fg=COLOR_SYSTEM,
            bg=bubble_bg, anchor=tk.W,
        )
        size_lbl.pack(fill=tk.X)

        inner.bind("<Button-3>", self._show_context_menu)
        name_lbl.bind("<Button-3>", self._show_context_menu)

    def _get_root(self):
        return self.winfo_toplevel()

    def _show_context_menu(self, event):
        menu = tk.Menu(self, tearoff=0)
        if self.msg.is_file:
            menu.add_command(label="打开文件", command=self._open_file)
            menu.add_command(label="另存文件...", command=self._save_file_as)
        else:
            menu.add_command(label="复制文本", command=self._copy_text)
        menu.add_separator()
        menu.add_command(label="复制消息内容", command=self._copy_full)
        menu.tk_popup(event.x_root, event.y_root)

    def _copy_text(self):
        root = self._get_root()
        root.clipboard_clear()
        root.clipboard_append(self.msg.content)

    def _copy_full(self):
        text = f"[{format_time(self.msg.timestamp)}] {self.msg.sender}: "
        if self.msg.is_file:
            text += f"[File] {self.msg.file_name} ({format_size(self.msg.file_size)})"
        else:
            text += self.msg.content
        root = self._get_root()
        root.clipboard_clear()
        root.clipboard_append(text)

    def _save_file_as(self):
        if not self.msg.file_path or not os.path.exists(self.msg.file_path):
            messagebox.showerror("错误", "文件不存在")
            return
        dest = filedialog.asksaveasfilename(
            initialfile=self.msg.file_name, title="保存文件",
        )
        if dest:
            try:
                shutil.copy2(self.msg.file_path, dest)
                messagebox.showinfo("成功", f"文件已保存到:\n{dest}")
            except Exception as e:
                messagebox.showerror("错误", f"保存失败: {e}")

    def _open_file(self, event=None):
        if self.on_open_file:
            self.on_open_file(self.msg)


class ChatView(tk.Frame):
    def __init__(self, parent, peer_ip: str, network: NetworkManager, on_open_file, on_back):
        super().__init__(parent)
        self.parent = parent
        self.peer_ip = peer_ip
        self.network = network
        self.on_open_file = on_open_file
        self.on_back = on_back

        self.messages: list[ChatMessage] = []
        self.selected_msg: Optional[ChatMessage] = None

        self._build_ui()
        self._setup_drag_drop()

    def _build_ui(self):
        top = tk.Frame(self, bg="#f0f0f0")
        top.pack(fill=tk.X)

        tk.Button(
            top, text="← 返回", command=self.on_back,
            font=("Segoe UI", 9), relief=tk.FLAT, padx=8,
        ).pack(side=tk.LEFT, pady=4, padx=4)

        self.title_lbl = tk.Label(
            top, text="聊天: ...",
            font=("Segoe UI", 11, "bold"), bg="#f0f0f0",
        )
        self.title_lbl.pack(side=tk.LEFT, padx=8, pady=4)
        self._update_title()

        separator = ttk.Separator(self, orient=tk.HORIZONTAL)
        separator.pack(fill=tk.X)

        canvas = tk.Canvas(self, bg="#ece5dd", highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=canvas.yview)
        self.msg_frame = tk.Frame(canvas, bg="#ece5dd")

        self.msg_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.msg_frame, anchor=tk.NW, tags="inner")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._drag_indicator = tk.Label(
            self, text="📁 拖放文件到此处发送",
            font=("Segoe UI", 10), fg="#888", bg="#fff8e1",
            relief=tk.SUNKEN, pady=6,
        )
        self._drag_indicator.pack(fill=tk.X, padx=0, pady=0)

        bottom = tk.Frame(self, bg="#f0f0f0")
        bottom.pack(fill=tk.X, side=tk.BOTTOM)

        input_frame = tk.Frame(bottom, bg="#ffffff", bd=1, relief=tk.SOLID)
        input_frame.pack(fill=tk.X, padx=6, pady=6)

        self.entry = tk.Text(input_frame, height=2, font=("Segoe UI", 10),
                             wrap=tk.WORD, relief=tk.FLAT, bd=0)
        self.entry.pack(fill=tk.X, padx=4, pady=4)
        self.entry.bind("<Return>", self._on_enter_key)
        self.entry.bind("<Shift-Return>", lambda e: None)
        self.entry.focus_set()

        btn_frame = tk.Frame(bottom, bg="#f0f0f0")
        btn_frame.pack(fill=tk.X, padx=6, pady=(0, 6))

        tk.Button(
            btn_frame, text="发送", command=self._send_message,
            font=("Segoe UI", 9), bg="#075E54", fg="white",
            padx=16, pady=2, relief=tk.FLAT,
        ).pack(side=tk.RIGHT, padx=(4, 0))

        tk.Button(
            btn_frame, text="📎 发送文件", command=self._send_file_dialog,
            font=("Segoe UI", 9), padx=12, pady=2, relief=tk.FLAT,
        ).pack(side=tk.RIGHT)

        self.progress_lbl = tk.Label(
            bottom, text="", font=("Segoe UI", 9),
            fg="#075E54", bg="#f0f0f0",
        )
        self.progress_lbl.pack(fill=tk.X, padx=8, pady=(0, 4))

    def _setup_drag_drop(self):
        try:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)
            self._drag_indicator.drop_target_register(DND_FILES)
            self._drag_indicator.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            self._drag_indicator.configure(text="📁 使用按钮发送文件")

    def _on_drop(self, event):
        files = []
        raw = event.data
        if raw:
            for part in raw.split():
                part = part.strip("{}")
                if os.path.isfile(part):
                    files.append(part)
        for f in files:
            threading.Thread(
                target=self.network.send_file,
                args=(self.peer_ip, f),
                daemon=True,
            ).start()

    def _on_enter_key(self, event):
        if not (event.state & 0x0001):
            self._send_message()
            return "break"

    def _send_message(self):
        text = self.entry.get("1.0", tk.END).strip()
        if not text:
            return
        self.entry.delete("1.0", tk.END)

        msg = ChatMessage(
            sender=self.network.username,
            content=text,
            timestamp=time.time(),
            is_self=True,
        )
        self._add_message(msg)
        threading.Thread(
            target=self._do_send_message, args=(text,), daemon=True,
        ).start()

    def _do_send_message(self, text):
        ok = self.network.send_message(self.peer_ip, text)
        if not ok:
            self.after(0, lambda: messagebox.showwarning("发送失败", f"无法连接到 {self.peer_ip}"))

    def _send_file_dialog(self):
        files = filedialog.askopenfilenames(title="选择要发送的文件")
        for f in files:
            threading.Thread(
                target=self.network.send_file,
                args=(self.peer_ip, f),
                daemon=True,
            ).start()

    def _add_message(self, msg: ChatMessage):
        self.messages.append(msg)
        bubble = ChatBubbleFrame(
            self.msg_frame, msg, on_open_file=self.on_open_file,
        )
        bubble.pack(fill=tk.X, padx=CHAT_PAD, pady=2)
        self.after(50, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        try:
            canvas = self.msg_frame.master
            canvas.yview_moveto(1.0)
        except:
            pass

    def receive_message(self, msg: ChatMessage):
        self.after(0, lambda: self._add_message(msg))

    def update_progress(self, progress: int, file_name: str, sender: str):
        info = f"{'发送' if sender == self.network.username else '接收'}: {file_name} - {progress}%"
        self.after(0, lambda: self.progress_lbl.configure(text=info))
        if progress >= 100:
            self.after(3000, lambda: self.progress_lbl.configure(text=""))

    def _update_title(self):
        peer = self.network.peers.get(self.peer_ip)
        if peer:
            self.title_lbl.configure(text=f"聊天: {peer.display_name}")

    def update_title(self):
        self._update_title()


class MainWindow:
    def __init__(self, username: str):
        self.username = username
        self.root = DnDTk()
        self.root.title(f"LanChat - {username}")
        self.root.geometry("800x550")
        self.root.minsize(600, 400)

        self.network = NetworkManager(
            username=username,
            on_message=self._on_message,
            on_file_progress=self._on_file_progress,
            on_peers_changed=self._on_peers_changed,
        )

        self.chat_views: dict[str, ChatView] = {}
        self.current_chat: Optional[ChatView] = None
        self.current_peer_ip: Optional[str] = None

        self._build_ui()
        self.network.start()

    def _build_ui(self):
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left = tk.Frame(paned, bg="#ffffff", width=220)
        paned.add(left, weight=0)

        tk.Label(
            left, text="在线用户", font=("Segoe UI", 12, "bold"),
            bg="#075E54", fg="white", padx=12, pady=8,
        ).pack(fill=tk.X)

        refresh_btn = tk.Button(
            left, text="🔄 刷新", command=self._refresh_peer_list,
            font=("Segoe UI", 9), relief=tk.FLAT, bg="#075E54", fg="white",
            padx=8, pady=2, cursor="hand2",
        )
        refresh_btn.pack(pady=(4, 0))

        self.peer_listbox = tk.Listbox(
            left, font=("Segoe UI", 10),
            bg="#ffffff", fg="#333333",
            selectbackground="#dcf8c6", selectforeground="#333333",
            activestyle=tk.NONE, bd=0, highlightthickness=0,
        )
        self.peer_listbox.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.peer_listbox.bind("<Double-Button-1>", self._on_peer_select)

        self.right_container = tk.Frame(paned, bg="#ece5dd")
        paned.add(self.right_container, weight=1)

        self.welcome_frame = tk.Frame(self.right_container, bg="#ece5dd")
        tk.Label(
            self.welcome_frame,
            text="👋 欢迎使用 LanChat\n\n双击左侧用户开始聊天\n拖放文件到聊天窗口发送文件",
            font=("Segoe UI", 14), bg="#ece5dd", fg="#888",
            justify=tk.CENTER,
        ).pack(expand=True)
        self.welcome_frame.pack(expand=True, fill=tk.BOTH)

        self._refresh_peer_list()
        self._start_peer_refresh_timer()

    def _show_welcome(self):
        for w in self.right_container.winfo_children():
            w.pack_forget()
        self.welcome_frame.pack(expand=True, fill=tk.BOTH)

    def _on_peer_select(self, event):
        sel = self.peer_listbox.curselection()
        if not sel:
            return
        text = self.peer_listbox.get(sel[0])
        try:
            peer_ip = text.split(" (")[-1].rstrip(")")
        except:
            return
        self._open_chat(peer_ip)

    def _open_chat(self, peer_ip: str):
        if peer_ip not in self.chat_views:
            cv = ChatView(
                self.right_container, peer_ip, self.network,
                on_open_file=self._open_file,
                on_back=self._show_welcome,
            )
            self.chat_views[peer_ip] = cv
        else:
            cv = self.chat_views[peer_ip]
            cv.update_title()
        for w in self.right_container.winfo_children():
            w.pack_forget()
        cv.pack(fill=tk.BOTH, expand=True)
        self.current_chat = cv
        self.current_peer_ip = peer_ip

    def _on_message(self, msg: ChatMessage, peer_ip: str):
        self.root.after(0, self._handle_message, msg, peer_ip)

    def _handle_message(self, msg: ChatMessage, peer_ip: str):
        if peer_ip in self.chat_views:
            self.chat_views[peer_ip].receive_message(msg)
        else:
            self._open_chat(peer_ip)
            self.chat_views[peer_ip].receive_message(msg)

    def _on_file_progress(self, progress: int, file_name: str, sender: str, peer_ip: str):
        self.root.after(0, self._handle_file_progress, progress, file_name, sender, peer_ip)

    def _handle_file_progress(self, progress: int, file_name: str, sender: str, peer_ip: str):
        if peer_ip in self.chat_views:
            self.chat_views[peer_ip].update_progress(progress, file_name, sender)

    def _on_peers_changed(self):
        self.root.after(0, self._refresh_peer_list)

    def _start_peer_refresh_timer(self):
        self._refresh_peer_list()
        self.root.after(2000, self._start_peer_refresh_timer)

    def _refresh_peer_list(self):
        self.peer_listbox.delete(0, tk.END)
        with self.network.peers_lock:
            for ip, peer in sorted(self.network.peers.items(), key=lambda x: x[1].name):
                status = "🟢" if peer.online else "🔴"
                display = f"{status} {peer.display_name}"
                self.peer_listbox.insert(tk.END, display)
                if not peer.online:
                    self.peer_listbox.itemconfig(tk.END, fg="#999")

    def _open_file(self, msg: ChatMessage):
        if msg.file_path and os.path.exists(msg.file_path):
            try:
                os.startfile(msg.file_path)
            except Exception:
                pass

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self):
        self.network.stop()
        self.root.destroy()
