"""
client.py — Instant Messaging Client (Tkinter GUI)

WhatsApp-inspired light theme with:
  • Card-style login screen
  • Sidebar with profile header, search, group chat + DM list
  • Avatar circles (colored initials, hashed per user)
  • Chat bubbles (right-aligned green for outgoing, white for incoming)
  • Day separators, time stamps, and ✓✓ ticks on own messages
  • Emoji picker popup
  • Online presence dot, unread badges, typing-into hints

Wire protocol is unchanged — works with the existing server.py.
"""

import socket
import threading
import queue
import json
import hashlib
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, font as tkfont
import datetime
import sys
import argparse
import struct
import ctypes

# ─── Configuration ────────────────────────────────────────────────────────────
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5555
BUFFER = 4096
MAX_MESSAGE_LEN = 500

_DISCONNECT = object()

def _enable_windows_dpi_awareness():
    """
    Make Tkinter crisp on Windows high-DPI displays.
    Without this, widgets/canvas can look blurry/pixelated due to bitmap scaling.
    """
    if sys.platform != "win32":
        return
    try:
        # Windows 8.1+ (best)
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor DPI aware
    except Exception:
        try:
            # Windows 7/8 fallback
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _configure_tk_scaling(root: tk.Tk):
    """
    Match Tk scaling to system DPI for sharper rendering.
    Tk uses 72 points/inch; Windows uses 96+ dpi. Scaling = dpi / 72.
    """
    try:
        dpi = float(root.winfo_fpixels("1i"))
        root.tk.call("tk", "scaling", dpi / 72.0)
    except Exception:
        pass


def _configure_default_fonts(root: tk.Tk):
    """Use modern fonts + consistent sizing."""
    try:
        for name, size, weight in [
            ("TkDefaultFont", 10, "normal"),
            ("TkTextFont", 10, "normal"),
            ("TkMenuFont", 9, "normal"),
            ("TkHeadingFont", 10, "bold"),
            ("TkCaptionFont", 9, "normal"),
        ]:
            f = tkfont.nametofont(name)
            f.configure(family="Segoe UI", size=size, weight=weight)
    except Exception:
        pass


def normalize_host(host: str) -> str:
    """Avoid localhost → IPv6 (::1) surprises on Windows; IM server is IPv4."""
    h = host.strip()
    if h.lower() == "localhost":
        return "127.0.0.1"
    return h


# ─── WhatsApp-inspired light palette ─────────────────────────────────────────
# Colors lifted from WhatsApp Web's modern light theme.
BG_APP          = "#F0F2F5"   # app frame / sidebar background
BG_SIDEBAR      = "#FFFFFF"   # sidebar surface
BG_CHAT         = "#EFEAE2"   # chat canvas background (the warm beige)
BG_HEADER       = "#F0F2F5"   # top bars
BG_INPUT_PANEL  = "#F0F2F5"   # bottom input strip
BG_ENTRY        = "#FFFFFF"   # text entry field
BG_HOVER        = "#F5F6F6"   # sidebar row hover
BG_SELECTED     = "#F0F2F5"   # sidebar row selected

BUBBLE_OUT      = "#D9FDD3"   # outgoing bubble (light green)
BUBBLE_IN       = "#FFFFFF"   # incoming bubble (white)
BUBBLE_SYS      = "#FFF3C4"   # system / info banner
BUBBLE_ERR      = "#FFD2D2"   # error banner
DAY_PILL_BG     = "#E1F2FB"   # day separator pill

ACCENT          = "#00A884"   # WhatsApp green (primary)
ACCENT_DARK     = "#008069"   # hover/dark green
ACCENT_TEAL     = "#005E54"   # legacy teal accent
TICK_READ       = "#53BDEB"   # blue ticks

TEXT_PRIMARY    = "#111B21"
TEXT_SECONDARY  = "#3B4A54"
TEXT_MUTED      = "#667781"
TEXT_FAINT      = "#8696A0"
TEXT_ON_ACCENT  = "#FFFFFF"

BORDER          = "#E9EDEF"
SHADOW          = "#D1D7DB"

SUCCESS         = "#00A884"
ERROR           = "#E53935"
WARN            = "#F59E0B"

# Avatar palette — consistent color per username via hash
AVATAR_COLORS = [
    "#00A884", "#53BDEB", "#7F66FF", "#F15C6D", "#F2994A",
    "#27AE60", "#2D9CDB", "#BB6BD9", "#EB5757", "#E0A800",
    "#1ABC9C", "#3498DB", "#9B59B6", "#E67E22", "#16A085",
]

EMOJIS = [
    "😀","😁","😂","🤣","😊","😍","😎","🤩","🥳","😉",
    "😘","🙃","🤔","😐","😴","🤤","🤗","🤝","👏","🙌",
    "👍","👎","🙏","💪","✌️","🤞","👌","🔥","✨","🎉",
    "💯","❤️","🧡","💛","💚","💙","💜","🖤","💔","💕",
    "🥺","😭","😤","😡","🤯","😱","🤐","🤫","🙄","😬",
    "🍕","🍔","🍟","🍩","☕","🍺","🍷","🎂","🍎","🥑",
    "⚽","🏀","🎮","🎵","📷","📱","💻","🚀","🌍","🌙",
]


def avatar_color_for(name: str) -> str:
    h = int(hashlib.md5(name.encode("utf-8")).hexdigest(), 16)
    return AVATAR_COLORS[h % len(AVATAR_COLORS)]


def initials_of(name: str) -> str:
    name = name.strip()
    if not name:
        return "?"
    parts = [p for p in name.split() if p]
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def make_avatar(parent, name: str, size: int = 40, font_size: int = 14, bg=None):
    """Return a Canvas with a colored circle + initials. `bg` matches surrounding widget bg."""
    if bg is None:
        bg = parent["bg"] if "bg" in parent.keys() else BG_SIDEBAR
    c = tk.Canvas(parent, width=size, height=size, bg=bg,
                  highlightthickness=0, bd=0)
    color = avatar_color_for(name) if name else TEXT_FAINT
    c.create_oval(1, 1, size - 1, size - 1, fill=color, outline="")
    c.create_text(size // 2, size // 2 + 1, text=initials_of(name),
                  fill="white", font=("Segoe UI", font_size, "bold"))
    return c


# ══════════════════════════════════════════════════════════════════════════════
#  Login Window
# ══════════════════════════════════════════════════════════════════════════════

class LoginWindow:
    """Card-style connect dialog."""

    def __init__(self):
        _enable_windows_dpi_awareness()
        self.root = tk.Tk()
        self.root.title("ChatWave — Connect")
        self.root.configure(bg=BG_APP)
        self.root.resizable(True, True)
        _configure_tk_scaling(self.root)
        _configure_default_fonts(self.root)

        self.username = tk.StringVar()
        self.host     = tk.StringVar(value=DEFAULT_HOST)
        self.port     = tk.StringVar(value=str(DEFAULT_PORT))
        self.result   = None

        self._build_ui()
        # Size AFTER widgets exist. On high-DPI, a fixed 440x560 can clip the button.
        self.root.update_idletasks()
        extra_w, extra_h = 60, 80
        req_w = self.root.winfo_reqwidth() + extra_w
        req_h = self.root.winfo_reqheight() + extra_h
        w = max(460, req_w)
        h = max(640, req_h)
        self._center(w, h)
        self.root.minsize(440, 620)
        self.root.mainloop()

    def _build_ui(self):
        # Outer padding wrapper
        wrap = tk.Frame(self.root, bg=BG_APP)
        wrap.pack(fill="both", expand=True, padx=24, pady=24)

        # White card
        card = tk.Frame(wrap, bg=BG_SIDEBAR, highlightthickness=1,
                        highlightbackground=BORDER)
        card.pack(fill="both", expand=True)

        # Brand
        brand = tk.Frame(card, bg=BG_SIDEBAR)
        brand.pack(pady=(28, 4))
        logo = tk.Canvas(brand, width=64, height=64, bg=BG_SIDEBAR,
                         highlightthickness=0)
        logo.pack()
        logo.create_oval(2, 2, 62, 62, fill=ACCENT, outline="")
        logo.create_text(32, 34, text="💬", font=("Segoe UI Emoji", 26))

        tk.Label(card, text="ChatWave",
                 font=("Segoe UI", 20, "bold"),
                 bg=BG_SIDEBAR, fg=TEXT_PRIMARY).pack(pady=(10, 2))
        tk.Label(card, text="Real-time messaging, made simple.",
                 font=("Segoe UI", 9),
                 bg=BG_SIDEBAR, fg=TEXT_MUTED).pack(pady=(0, 18))

        # Fields
        for label, var, placeholder in [
            ("Display name", self.username, "e.g. Bilal"),
            ("Server host",  self.host,     "127.0.0.1"),
            ("Port",         self.port,     "5555"),
        ]:
            row = tk.Frame(card, bg=BG_SIDEBAR)
            row.pack(fill="x", padx=32, pady=(6, 2))
            tk.Label(row, text=label.upper(),
                     font=("Segoe UI", 8, "bold"),
                     bg=BG_SIDEBAR, fg=TEXT_MUTED).pack(anchor="w")
            e = tk.Entry(row, textvariable=var,
                         font=("Segoe UI", 11),
                         bg=BG_ENTRY, fg=TEXT_PRIMARY,
                         insertbackground=TEXT_PRIMARY,
                         relief="flat", bd=10,
                         highlightthickness=1,
                         highlightbackground=BORDER,
                         highlightcolor=ACCENT)
            e.pack(fill="x", pady=(4, 6), ipady=4)
            if label == "Display name":
                e.focus_set()

        # Connect button
        btn = tk.Button(card, text="Start chatting →",
                        font=("Segoe UI", 11, "bold"),
                        bg=ACCENT, fg=TEXT_ON_ACCENT,
                        activebackground=ACCENT_DARK,
                        activeforeground=TEXT_ON_ACCENT,
                        relief="flat", bd=0, cursor="hand2",
                        command=self._connect)
        btn.pack(fill="x", padx=32, pady=(18, 8), ipady=10)
        self._add_hover(btn, ACCENT, ACCENT_DARK)

        tk.Label(card, text="Press Enter to connect",
                 font=("Segoe UI", 8),
                 bg=BG_SIDEBAR, fg=TEXT_FAINT).pack(pady=(2, 22))

        self.root.bind("<Return>", lambda _: self._connect())

    @staticmethod
    def _add_hover(widget, base, hover):
        widget.bind("<Enter>", lambda _: widget.configure(bg=hover))
        widget.bind("<Leave>", lambda _: widget.configure(bg=base))

    def _connect(self):
        uname  = self.username.get().strip()
        host   = self.host.get().strip()
        port_s = self.port.get().strip()

        if not uname:
            messagebox.showerror("Error", "Display name cannot be empty.", parent=self.root)
            return
        if not host:
            messagebox.showerror("Error", "Host cannot be empty.", parent=self.root)
            return
        try:
            port = int(port_s)
        except ValueError:
            messagebox.showerror("Error", "Port must be a number.", parent=self.root)
            return

        self.result = (uname, host, port)
        self.root.destroy()

    def _center(self, w, h):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")


# ══════════════════════════════════════════════════════════════════════════════
#  Scrollable Chat Bubble Area
# ══════════════════════════════════════════════════════════════════════════════

class ChatArea(tk.Frame):
    """Vertically scrollable area that hosts message bubbles + day separators."""

    def __init__(self, master, **kw):
        super().__init__(master, bg=BG_CHAT, **kw)
        self.canvas = tk.Canvas(self, bg=BG_CHAT, highlightthickness=0, bd=0)
        self.vbar   = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.vbar.pack(side="right", fill="y")

        self.inner = tk.Frame(self.canvas, bg=BG_CHAT)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        # Cross-platform mousewheel
        self.canvas.bind("<Enter>", lambda _: self._bind_wheel())
        self.canvas.bind("<Leave>", lambda _: self._unbind_wheel())

        self._last_day = None  # YYYY-MM-DD of last separator

    def _on_canvas_resize(self, event):
        self.canvas.itemconfigure(self._win, width=event.width)

    def _bind_wheel(self):
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        self.canvas.bind_all("<Button-4>",  lambda e: self.canvas.yview_scroll(-3, "units"))
        self.canvas.bind_all("<Button-5>",  lambda e: self.canvas.yview_scroll( 3, "units"))

    def _unbind_wheel(self):
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _on_wheel(self, event):
        delta = -1 * (event.delta // 120) if event.delta else 0
        if delta:
            self.canvas.yview_scroll(delta * 3, "units")

    # ── Public API ──────────────────────────────────────────────────────────

    def clear(self):
        for child in self.inner.winfo_children():
            child.destroy()
        self._last_day = None

    def scroll_to_bottom(self):
        self.update_idletasks()
        self.canvas.yview_moveto(1.0)

    def add_day_separator(self, day_label: str):
        wrap = tk.Frame(self.inner, bg=BG_CHAT)
        wrap.pack(fill="x", pady=(10, 6))
        pill = tk.Label(wrap, text=f"  {day_label}  ",
                        font=("Segoe UI", 8, "bold"),
                        bg=DAY_PILL_BG, fg=TEXT_SECONDARY,
                        padx=10, pady=3)
        pill.pack()

    def add_system(self, text: str, kind: str = "info"):
        bg = BUBBLE_SYS if kind == "info" else BUBBLE_ERR
        fg = TEXT_SECONDARY if kind == "info" else "#7B1F1F"
        wrap = tk.Frame(self.inner, bg=BG_CHAT)
        wrap.pack(fill="x", pady=4)
        lbl = tk.Label(wrap, text=text,
                       font=("Segoe UI", 9),
                       bg=bg, fg=fg, padx=12, pady=6,
                       wraplength=520, justify="center")
        lbl.pack()

    def add_bubble(self, *, sender: str, body: str, ts: str, is_own: bool,
                   show_sender: bool, is_dm: bool = False):
        """Add a message bubble. show_sender controls whether the sender label is rendered."""
        side = "right" if is_own else "left"
        bg   = BUBBLE_OUT if is_own else BUBBLE_IN

        outer = tk.Frame(self.inner, bg=BG_CHAT)
        outer.pack(fill="x", padx=12, pady=2)

        # spacer to push bubble to the correct side
        if is_own:
            tk.Frame(outer, bg=BG_CHAT).pack(side="left", expand=True, fill="x")

        # Row holds optional avatar + bubble
        row = tk.Frame(outer, bg=BG_CHAT)
        row.pack(side=side)

        if not is_own and show_sender:
            av = make_avatar(row, sender, size=32, font_size=11, bg=BG_CHAT)
            av.pack(side="left", padx=(0, 6), anchor="n", pady=(2, 0))

        bubble = tk.Frame(row, bg=bg, highlightthickness=0)
        bubble.pack(side="left")

        # Sender label (only for incoming, only when grouping breaks)
        if not is_own and show_sender:
            tk.Label(bubble, text=sender,
                     font=("Segoe UI", 9, "bold"),
                     bg=bg, fg=avatar_color_for(sender),
                     anchor="w").pack(fill="x", padx=10, pady=(6, 0))

        # DM tag chip
        if is_dm:
            tk.Label(bubble, text="🔒  Direct message",
                     font=("Segoe UI", 7, "bold"),
                     bg=bg, fg=TEXT_MUTED).pack(anchor="w", padx=10, pady=(4, 0))

        # Message text
        msg = tk.Label(bubble, text=body,
                       font=("Segoe UI Emoji", 11),
                       bg=bg, fg=TEXT_PRIMARY,
                       wraplength=520, justify="left", anchor="w")
        msg.pack(fill="x", padx=10, pady=(4, 2))

        # Meta row (time + ticks)
        meta = tk.Frame(bubble, bg=bg)
        meta.pack(anchor="e", padx=8, pady=(0, 6))
        tk.Label(meta, text=ts,
                 font=("Segoe UI", 7),
                 bg=bg, fg=TEXT_MUTED).pack(side="left")
        if is_own:
            tk.Label(meta, text=" ✓✓",
                     font=("Segoe UI", 8, "bold"),
                     bg=bg, fg=TICK_READ).pack(side="left")

        if not is_own:
            tk.Frame(outer, bg=BG_CHAT).pack(side="left", expand=True, fill="x")


# ══════════════════════════════════════════════════════════════════════════════
#  Main Chat Window
# ══════════════════════════════════════════════════════════════════════════════

class ChatWindow:
    def __init__(self, username: str, host: str, port: int):
        self.username = username
        self.host = normalize_host(host)
        self.port = port
        self.sock: socket.socket | None = None
        self.running = False
        self._live = False
        self._disconnect_notified = False
        self._ui_queue = queue.Queue()
        self.target = "ALL"

        # history[conv] = list of dicts {sender, body, ts, dt, is_own, is_dm}
        self._history: dict[str, list[dict]] = {"ALL": []}
        self._online_users: list[str] = []
        self._unread: dict[str, int] = {}
        self._sidebar_rows: dict[str, dict] = {}   # name -> {frame, badge_var, ...}
        self._emoji_popup: tk.Toplevel | None = None

        _enable_windows_dpi_awareness()
        self.root = tk.Tk()
        self.root.title(f"ChatWave — {username}")
        self.root.configure(bg=BG_APP)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        _configure_tk_scaling(self.root)
        _configure_default_fonts(self.root)
        self._center(1020, 680)
        self.root.minsize(820, 520)

        self._build_ui()
        self._connect_to_server()
        self.root.after(0, self._poll_ui_queue)
        self.root.mainloop()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.root.columnconfigure(0, weight=0, minsize=320)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_chat_pane()

    def _build_sidebar(self):
        sidebar = tk.Frame(self.root, bg=BG_SIDEBAR, width=320,
                           highlightthickness=1, highlightbackground=BORDER)
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(2, weight=1)

        # Profile header
        header = tk.Frame(sidebar, bg=BG_HEADER, height=64)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)

        av = make_avatar(header, self.username, size=42, font_size=14, bg=BG_HEADER)
        av.pack(side="left", padx=14, pady=11)

        name_box = tk.Frame(header, bg=BG_HEADER)
        name_box.pack(side="left", fill="x", expand=True, pady=10)
        tk.Label(name_box, text=self.username,
                 font=("Segoe UI", 11, "bold"),
                 bg=BG_HEADER, fg=TEXT_PRIMARY, anchor="w").pack(fill="x")

        # Connection badge (dot + text)
        status_row = tk.Frame(name_box, bg=BG_HEADER)
        status_row.pack(fill="x")
        self.status_canvas = tk.Canvas(status_row, width=10, height=10,
                                       bg=BG_HEADER, highlightthickness=0)
        self.status_canvas.pack(side="left", pady=(2, 0))
        self._dot = self.status_canvas.create_oval(1, 1, 9, 9, fill=ERROR, outline="")
        self.conn_var = tk.StringVar(value="connecting…")
        tk.Label(status_row, textvariable=self.conn_var,
                 font=("Segoe UI", 8),
                 bg=BG_HEADER, fg=TEXT_MUTED).pack(side="left", padx=(6, 0))

        # Search (visual only — filters DM list)
        search_wrap = tk.Frame(sidebar, bg=BG_SIDEBAR)
        search_wrap.grid(row=1, column=0, sticky="ew", padx=10, pady=(8, 6))
        search_inner = tk.Frame(search_wrap, bg=BG_HEADER, highlightthickness=1,
                                highlightbackground=BORDER)
        search_inner.pack(fill="x")
        tk.Label(search_inner, text="🔍", font=("Segoe UI Emoji", 10),
                 bg=BG_HEADER, fg=TEXT_MUTED).pack(side="left", padx=(10, 4), pady=6)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refresh_user_rows())
        tk.Entry(search_inner, textvariable=self.search_var,
                 font=("Segoe UI", 10),
                 bg=BG_HEADER, fg=TEXT_PRIMARY,
                 insertbackground=TEXT_PRIMARY,
                 relief="flat", bd=0).pack(side="left", fill="x", expand=True,
                                           padx=(0, 10), pady=6, ipady=2)

        # Scrollable list of chats (group + DMs)
        list_wrap = tk.Frame(sidebar, bg=BG_SIDEBAR)
        list_wrap.grid(row=2, column=0, sticky="nsew")
        list_wrap.columnconfigure(0, weight=1)
        list_wrap.rowconfigure(0, weight=1)

        list_canvas = tk.Canvas(list_wrap, bg=BG_SIDEBAR, highlightthickness=0)
        list_canvas.grid(row=0, column=0, sticky="nsew")
        list_scroll = ttk.Scrollbar(list_wrap, orient="vertical",
                                    command=list_canvas.yview)
        list_scroll.grid(row=0, column=1, sticky="ns")
        list_canvas.configure(yscrollcommand=list_scroll.set)

        self.list_inner = tk.Frame(list_canvas, bg=BG_SIDEBAR)
        list_canvas.create_window((0, 0), window=self.list_inner, anchor="nw")
        self.list_inner.bind("<Configure>",
            lambda e: list_canvas.configure(scrollregion=list_canvas.bbox("all")))
        list_canvas.bind("<Configure>",
            lambda e: list_canvas.itemconfigure(list_canvas.find_all()[0], width=e.width))

        # Pinned: Group chat row
        self._build_group_row()

        # DM list separator
        sep = tk.Frame(self.list_inner, bg=BG_SIDEBAR)
        sep.pack(fill="x", pady=(6, 2))
        tk.Label(sep, text="ONLINE NOW",
                 font=("Segoe UI", 8, "bold"),
                 bg=BG_SIDEBAR, fg=TEXT_MUTED).pack(side="left", padx=14)
        self.online_count_var = tk.StringVar(value="0")
        tk.Label(sep, textvariable=self.online_count_var,
                 font=("Segoe UI", 8, "bold"),
                 bg=BG_SIDEBAR, fg=ACCENT_DARK).pack(side="right", padx=14)

        self.users_container = tk.Frame(self.list_inner, bg=BG_SIDEBAR)
        self.users_container.pack(fill="x")

        self.empty_label = tk.Label(self.list_inner,
                                    text="✨  You're the only one here.\nInvite a friend to chat!",
                                    font=("Segoe UI", 9),
                                    bg=BG_SIDEBAR, fg=TEXT_MUTED, justify="center")
        self.empty_label.pack(pady=20)

    def _build_group_row(self):
        row = self._make_chat_row(parent=self.list_inner,
                                  name="ALL",
                                  display="Group Chat",
                                  subtitle="Everyone online",
                                  emoji_avatar="👥",
                                  is_group=True)
        row["frame"].pack(fill="x")
        self._sidebar_rows["ALL"] = row
        self._highlight_active_row()

    def _make_chat_row(self, *, parent, name, display, subtitle,
                       emoji_avatar=None, is_group=False):
        frame = tk.Frame(parent, bg=BG_SIDEBAR, cursor="hand2", height=64)
        frame.pack_propagate(False)

        # Avatar
        if emoji_avatar:
            av = tk.Canvas(frame, width=42, height=42, bg=BG_SIDEBAR, highlightthickness=0)
            av.create_oval(1, 1, 41, 41, fill=ACCENT, outline="")
            av.create_text(21, 23, text=emoji_avatar, font=("Segoe UI Emoji", 18))
        else:
            av = make_avatar(frame, name, size=42, font_size=14, bg=BG_SIDEBAR)
        av.pack(side="left", padx=(12, 10), pady=10)

        # Text column
        col = tk.Frame(frame, bg=BG_SIDEBAR)
        col.pack(side="left", fill="both", expand=True, pady=10)

        title_row = tk.Frame(col, bg=BG_SIDEBAR)
        title_row.pack(fill="x")
        title_lbl = tk.Label(title_row, text=display,
                             font=("Segoe UI", 10, "bold"),
                             bg=BG_SIDEBAR, fg=TEXT_PRIMARY, anchor="w")
        title_lbl.pack(side="left")

        sub_row = tk.Frame(col, bg=BG_SIDEBAR)
        sub_row.pack(fill="x", pady=(2, 0))
        sub_var = tk.StringVar(value=subtitle)
        sub_lbl = tk.Label(sub_row, textvariable=sub_var,
                           font=("Segoe UI", 9),
                           bg=BG_SIDEBAR, fg=TEXT_MUTED, anchor="w")
        sub_lbl.pack(side="left")

        # Right side: badge
        right = tk.Frame(frame, bg=BG_SIDEBAR)
        right.pack(side="right", padx=12)
        badge_var = tk.StringVar(value="")
        badge = tk.Label(right, textvariable=badge_var,
                         font=("Segoe UI", 8, "bold"),
                         bg=ACCENT, fg=TEXT_ON_ACCENT, padx=7, pady=1)
        # Hidden until needed
        # We toggle via _refresh_user_rows / _refresh_group_row

        widgets = [frame, av, col, title_row, title_lbl, sub_row, sub_lbl, right, badge]

        def on_enter(_=None):
            if self.target != name:
                for w in widgets:
                    try: w.configure(bg=BG_HOVER)
                    except tk.TclError: pass

        def on_leave(_=None):
            if self.target != name:
                for w in widgets:
                    try: w.configure(bg=BG_SIDEBAR)
                    except tk.TclError: pass

        def on_click(_=None):
            self._set_target(name)

        for w in widgets:
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
            w.bind("<Button-1>", on_click)

        return {
            "frame": frame, "widgets": widgets,
            "title_lbl": title_lbl, "sub_var": sub_var,
            "badge": badge, "badge_var": badge_var, "right": right,
            "is_group": is_group,
        }

    def _build_chat_pane(self):
        right = tk.Frame(self.root, bg=BG_APP)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=0)
        right.rowconfigure(1, weight=1)
        right.rowconfigure(2, weight=0)
        right.columnconfigure(0, weight=1)

        # Top header
        header = tk.Frame(right, bg=BG_HEADER, height=64,
                          highlightthickness=1, highlightbackground=BORDER)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)

        self._chat_avatar_holder = tk.Frame(header, bg=BG_HEADER)
        self._chat_avatar_holder.pack(side="left", padx=14, pady=11)

        title_box = tk.Frame(header, bg=BG_HEADER)
        title_box.pack(side="left", fill="x", expand=True, pady=10)
        self.header_var = tk.StringVar(value="Group Chat")
        tk.Label(title_box, textvariable=self.header_var,
                 font=("Segoe UI", 12, "bold"),
                 bg=BG_HEADER, fg=TEXT_PRIMARY, anchor="w").pack(fill="x")
        self.subheader_var = tk.StringVar(value="Everyone online can see your messages")
        tk.Label(title_box, textvariable=self.subheader_var,
                 font=("Segoe UI", 8),
                 bg=BG_HEADER, fg=TEXT_MUTED, anchor="w").pack(fill="x")

        self._refresh_chat_header_avatar()

        # Chat bubbles area
        self.chat_area = ChatArea(right)
        self.chat_area.grid(row=1, column=0, sticky="nsew")

        # Input panel
        panel = tk.Frame(right, bg=BG_INPUT_PANEL,
                         highlightthickness=1, highlightbackground=BORDER)
        panel.grid(row=2, column=0, sticky="ew")
        panel.columnconfigure(1, weight=1)

        # Emoji button
        self.emoji_btn = tk.Label(panel, text="😊",
                                  font=("Segoe UI Emoji", 16),
                                  bg=BG_INPUT_PANEL, fg=TEXT_MUTED,
                                  cursor="hand2", padx=10)
        self.emoji_btn.grid(row=0, column=0, padx=(8, 4), pady=10)
        self.emoji_btn.bind("<Button-1>", lambda _: self._toggle_emoji_picker())

        # Entry
        entry_wrap = tk.Frame(panel, bg=BG_ENTRY,
                              highlightthickness=1, highlightbackground=BORDER)
        entry_wrap.grid(row=0, column=1, sticky="ew", pady=10, padx=(0, 8))
        self.msg_entry = tk.Entry(entry_wrap,
                                  font=("Segoe UI Emoji", 11),
                                  bg=BG_ENTRY, fg=TEXT_PRIMARY,
                                  insertbackground=TEXT_PRIMARY,
                                  relief="flat", bd=0)
        self.msg_entry.pack(fill="x", padx=12, pady=8, ipady=2)
        self.msg_entry.bind("<Return>", lambda _: self._send_message())
        self.msg_entry.bind("<Escape>", lambda _: self._set_target("ALL"))

        # Send button (circular)
        send_canvas = tk.Canvas(panel, width=44, height=44,
                                bg=BG_INPUT_PANEL, highlightthickness=0,
                                cursor="hand2")
        send_canvas.grid(row=0, column=2, padx=(0, 12), pady=10)
        circle = send_canvas.create_oval(2, 2, 42, 42, fill=ACCENT, outline="")
        arrow = send_canvas.create_text(22, 22, text="➤", fill="white",
                                        font=("Segoe UI", 14, "bold"))
        def hover_in(_=None):  send_canvas.itemconfig(circle, fill=ACCENT_DARK)
        def hover_out(_=None): send_canvas.itemconfig(circle, fill=ACCENT)
        send_canvas.bind("<Enter>", hover_in)
        send_canvas.bind("<Leave>", hover_out)
        send_canvas.bind("<Button-1>", lambda _: self._send_message())
        # also bind the arrow text item
        send_canvas.tag_bind(arrow, "<Button-1>", lambda _: self._send_message())

    def _refresh_chat_header_avatar(self):
        for w in self._chat_avatar_holder.winfo_children():
            w.destroy()
        if self.target == "ALL":
            av = tk.Canvas(self._chat_avatar_holder, width=42, height=42,
                           bg=BG_HEADER, highlightthickness=0)
            av.create_oval(1, 1, 41, 41, fill=ACCENT, outline="")
            av.create_text(21, 23, text="👥", font=("Segoe UI Emoji", 18))
        else:
            av = make_avatar(self._chat_avatar_holder, self.target,
                             size=42, font_size=14, bg=BG_HEADER)
        av.pack()

    # ── Networking ────────────────────────────────────────────────────────────

    def _connect_to_server(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, int(self.port)))
            try:
                self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            self.running = True
            self._send_packet({"type": "login", "body": self.username})
            t = threading.Thread(target=self._receive_loop, daemon=True)
            t.start()
        except OSError as e:
            messagebox.showerror("Connection Failed", str(e))
            self.root.destroy()

    def _poll_ui_queue(self):
        try:
            while True:
                item = self._ui_queue.get_nowait()
                if item is _DISCONNECT:
                    self._on_disconnect()
                elif isinstance(item, dict):
                    self._handle_packet(item)
        except queue.Empty:
            pass
        try:
            self.root.after(30, self._poll_ui_queue)
        except tk.TclError:
            pass

    def _receive_loop(self):
        inbuf = bytearray()
        try:
            while self.running:
                chunk = self.sock.recv(BUFFER)
                if not chunk:
                    break
                inbuf.extend(chunk)
                while len(inbuf) >= 4:
                    msg_len = struct.unpack("!I", inbuf[:4])[0]
                    if len(inbuf) < 4 + msg_len:
                        break
                    payload = bytes(inbuf[4:4 + msg_len])
                    del inbuf[:4 + msg_len]
                    try:
                        pkt = json.loads(payload.decode("utf-8", errors="replace"))
                    except json.JSONDecodeError:
                        continue
                    if isinstance(pkt, dict):
                        self._ui_queue.put(pkt)
        except OSError:
            pass
        finally:
            self.running = False
            self._ui_queue.put(_DISCONNECT)

    def _handle_packet(self, pkt: dict):
        ptype  = pkt.get("type", "msg")
        sender = pkt.get("sender", "?")
        body   = pkt.get("body", "")
        ts     = pkt.get("timestamp", "")
        scope  = pkt.get("scope")
        to     = pkt.get("to")

        self._mark_live()

        if ptype == "list":
            users = body if isinstance(body, list) else self._safe_json_list(body)
            self._update_user_list(users)
            return

        if ptype == "info":
            self._add_system_to_current(f"ℹ️  {body}", "info")
            return

        if ptype == "error":
            self._add_system_to_current(f"⚠️  {body}", "error")
            return

        if ptype == "msg":
            is_dm = (scope == "dm" and isinstance(to, str) and to)
            if is_dm:
                conv = str(to) if sender == self.username else str(sender)
            else:
                conv = "ALL"

            entry = {
                "sender":  sender,
                "body":    body,
                "ts":      ts,
                "dt":      datetime.datetime.now(),
                "is_own":  sender == self.username,
                "is_dm":   bool(is_dm),
            }
            self._history.setdefault(conv, []).append(entry)

            # Unread bookkeeping
            if conv != self.target and not entry["is_own"]:
                self._unread[conv] = self._unread.get(conv, 0) + 1
                if conv == "ALL":
                    self._refresh_group_row()
                else:
                    self._refresh_user_rows()

            # Update sidebar subtitle preview for that conv
            self._update_row_preview(conv, sender, body)

            if self.target == conv:
                self._render_single_message(entry, conv)

    @staticmethod
    def _safe_json_list(body) -> list:
        try:
            v = json.loads(body)
            return v if isinstance(v, list) else []
        except Exception:
            return []

    # ── Sidebar / chat row helpers ───────────────────────────────────────────

    def _mark_live(self):
        if self._live:
            return
        self._live = True
        self.status_canvas.itemconfig(self._dot, fill=SUCCESS)
        self.conn_var.set("online")

    def _update_user_list(self, users: list):
        self._online_users = [u for u in users if u != self.username]
        # Forget unread for users who went offline
        online = set(self._online_users)
        for k in list(self._unread.keys()):
            if k != "ALL" and k not in online:
                self._unread.pop(k, None)
        self._refresh_user_rows()
        self._refresh_group_row()

    def _refresh_user_rows(self):
        # Rebuild row widgets each refresh — list is small and this keeps state simple.
        for child in self.users_container.winfo_children():
            child.destroy()

        query = self.search_var.get().strip().lower()
        visible = [u for u in self._online_users if query in u.lower()]

        if not self._online_users:
            self.empty_label.pack(pady=20)
        else:
            self.empty_label.pack_forget()

        self.online_count_var.set(str(len(self._online_users)))

        for u in visible:
            unread = self._unread.get(u, 0)
            preview = self._last_preview(u) or "Tap to send a direct message"
            row = self._make_chat_row(parent=self.users_container,
                                      name=u, display=u,
                                      subtitle=preview)
            row["frame"].pack(fill="x")
            self._sidebar_rows[u] = row
            self._apply_badge(row, unread)

        self._highlight_active_row()

    def _refresh_group_row(self):
        row = self._sidebar_rows.get("ALL")
        if not row:
            return
        unread = self._unread.get("ALL", 0)
        preview = self._last_preview("ALL") or "Everyone online"
        row["sub_var"].set(preview)
        self._apply_badge(row, unread)
        self._highlight_active_row()

    def _update_row_preview(self, conv: str, sender: str, body: str):
        snippet = body if len(body) <= 40 else body[:37] + "…"
        if conv == "ALL":
            text = f"{sender}: {snippet}" if sender != self.username else f"You: {snippet}"
        else:
            text = f"You: {snippet}" if sender == self.username else snippet
        row = self._sidebar_rows.get(conv)
        if row:
            row["sub_var"].set(text)

    def _last_preview(self, conv: str) -> str | None:
        h = self._history.get(conv)
        if not h:
            return None
        last = h[-1]
        s = last["body"]
        snip = s if len(s) <= 40 else s[:37] + "…"
        if conv == "ALL":
            return f"{last['sender']}: {snip}" if not last["is_own"] else f"You: {snip}"
        return f"You: {snip}" if last["is_own"] else snip

    def _apply_badge(self, row: dict, count: int):
        badge = row["badge"]
        var = row["badge_var"]
        if count > 0:
            var.set(str(count))
            badge.pack(side="right")
        else:
            var.set("")
            badge.pack_forget()

    def _highlight_active_row(self):
        for name, row in self._sidebar_rows.items():
            color = BG_SELECTED if name == self.target else BG_SIDEBAR
            for w in row["widgets"]:
                try: w.configure(bg=color)
                except tk.TclError: pass
            # Badge always keeps its accent green bg
            row["badge"].configure(bg=ACCENT)
            # Right wrapper matches the row bg
            row["right"].configure(bg=color)

    # ── Conversation switching / rendering ───────────────────────────────────

    def _set_target(self, target: str):
        if target != "ALL" and target not in self._online_users and target not in self._history:
            return
        self.target = target
        self._unread[target] = 0
        if target == "ALL":
            self.header_var.set("Group Chat")
            self.subheader_var.set("Everyone online can see your messages")
        else:
            self.header_var.set(target)
            self.subheader_var.set("Direct message — Esc to go back to Group")
        self._refresh_chat_header_avatar()
        self._refresh_group_row()
        self._refresh_user_rows()
        self._render_history(target)
        self.msg_entry.focus_set()

    def _render_history(self, conv: str):
        self.chat_area.clear()
        history = self._history.get(conv, [])
        prev_sender = None
        prev_day    = None
        for entry in history:
            day_label = self._day_label(entry["dt"])
            if day_label != prev_day:
                self.chat_area.add_day_separator(day_label)
                prev_day = day_label
                prev_sender = None
            show_sender = (conv == "ALL") and (not entry["is_own"]) and (prev_sender != entry["sender"])
            self.chat_area.add_bubble(
                sender=entry["sender"], body=entry["body"], ts=entry["ts"],
                is_own=entry["is_own"], show_sender=show_sender, is_dm=entry["is_dm"],
            )
            prev_sender = entry["sender"]
        if not history:
            self._render_empty_state(conv)
        self.chat_area.scroll_to_bottom()

    def _render_empty_state(self, conv: str):
        wrap = tk.Frame(self.chat_area.inner, bg=BG_CHAT)
        wrap.pack(fill="x", pady=80)
        tk.Label(wrap, text="💭", font=("Segoe UI Emoji", 40),
                 bg=BG_CHAT, fg=TEXT_FAINT).pack()
        title = "Start the conversation" if conv != "ALL" else "Welcome to the Group Chat"
        sub = (f"Say hi to {conv} 👋" if conv != "ALL"
               else "Send a message — everyone online will see it.")
        tk.Label(wrap, text=title, font=("Segoe UI", 12, "bold"),
                 bg=BG_CHAT, fg=TEXT_SECONDARY).pack(pady=(8, 2))
        tk.Label(wrap, text=sub, font=("Segoe UI", 9),
                 bg=BG_CHAT, fg=TEXT_MUTED).pack()

    def _render_single_message(self, entry: dict, conv: str):
        # Insert day separator if needed
        day_label = self._day_label(entry["dt"])
        if self.chat_area._last_day != day_label:
            self.chat_area.add_day_separator(day_label)
            self.chat_area._last_day = day_label

        # Should we show sender? only for group chat & incoming
        history = self._history.get(conv, [])
        show_sender = False
        if conv == "ALL" and not entry["is_own"]:
            # Find prior message
            prior = history[-2] if len(history) >= 2 else None
            show_sender = (prior is None) or (prior["sender"] != entry["sender"])

        self.chat_area.add_bubble(
            sender=entry["sender"], body=entry["body"], ts=entry["ts"],
            is_own=entry["is_own"], show_sender=show_sender, is_dm=entry["is_dm"],
        )
        self.chat_area.scroll_to_bottom()

    def _add_system_to_current(self, text: str, kind: str):
        self.chat_area.add_system(text, kind=kind)
        self.chat_area.scroll_to_bottom()

    @staticmethod
    def _day_label(dt: datetime.datetime) -> str:
        today = datetime.date.today()
        d = dt.date()
        if d == today:
            return "Today"
        if d == today - datetime.timedelta(days=1):
            return "Yesterday"
        return dt.strftime("%A, %d %B")

    # ── Sending ──────────────────────────────────────────────────────────────

    def _send_message(self):
        body = self.msg_entry.get().strip()
        if not body or not self.running:
            return
        if len(body) > MAX_MESSAGE_LEN:
            self._add_system_to_current(
                f"⚠️  Message too long (max {MAX_MESSAGE_LEN} characters).", "error")
            return
        try:
            self._send_packet({"type": "msg", "to": self.target, "body": body})
        except OSError:
            self._add_system_to_current("Failed to send message.", "error")
        self.msg_entry.delete(0, "end")

    def _send_packet(self, packet: dict):
        payload = json.dumps(packet, ensure_ascii=False).encode("utf-8")
        frame = struct.pack("!I", len(payload)) + payload
        self.sock.sendall(frame)

    # ── Emoji picker ─────────────────────────────────────────────────────────

    def _toggle_emoji_picker(self):
        if self._emoji_popup and tk.Toplevel.winfo_exists(self._emoji_popup):
            self._emoji_popup.destroy()
            self._emoji_popup = None
            return
        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.configure(bg=BG_SIDEBAR, highlightthickness=1,
                        highlightbackground=BORDER)
        # Position above emoji button
        self.emoji_btn.update_idletasks()
        x = self.emoji_btn.winfo_rootx()
        y = self.emoji_btn.winfo_rooty() - 250
        popup.geometry(f"320x240+{x}+{y}")

        tk.Label(popup, text="Pick an emoji",
                 font=("Segoe UI", 9, "bold"),
                 bg=BG_SIDEBAR, fg=TEXT_SECONDARY).pack(anchor="w", padx=10, pady=(8, 4))

        grid = tk.Frame(popup, bg=BG_SIDEBAR)
        grid.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        cols = 10
        for i, em in enumerate(EMOJIS):
            r, c = divmod(i, cols)
            b = tk.Label(grid, text=em, font=("Segoe UI Emoji", 14),
                         bg=BG_SIDEBAR, cursor="hand2", padx=4, pady=2)
            b.grid(row=r, column=c, sticky="nsew")
            b.bind("<Enter>", lambda _e, w=b: w.configure(bg=BG_HOVER))
            b.bind("<Leave>", lambda _e, w=b: w.configure(bg=BG_SIDEBAR))
            b.bind("<Button-1>", lambda _e, sym=em: self._insert_emoji(sym))

        # Click-outside closes
        def on_click_outside(event):
            if event.widget.winfo_toplevel() is not popup:
                if self._emoji_popup:
                    self._emoji_popup.destroy()
                    self._emoji_popup = None
                self.root.unbind("<Button-1>", _bind_id)

        _bind_id = self.root.bind("<Button-1>", on_click_outside, add="+")
        self._emoji_popup = popup

    def _insert_emoji(self, sym: str):
        self.msg_entry.insert("insert", sym)
        self.msg_entry.focus_set()

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def _on_disconnect(self):
        if self._disconnect_notified:
            return
        self._disconnect_notified = True
        self.status_canvas.itemconfig(self._dot, fill=ERROR)
        self._live = False
        self.conn_var.set("offline")
        self._add_system_to_current("⚠️  Disconnected from server.", "error")

    def _on_close(self):
        self._disconnect_notified = True
        self.running = False
        if self.sock:
            try:
                self._send_packet({"type": "logout"})
                self.sock.close()
            except OSError:
                pass
        self.root.destroy()

    def _center(self, w, h):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")


# ══════════════════════════════════════════════════════════════════════════════
#  Entry point
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="ChatWave — Instant Messaging Client")
    parser.add_argument("--username", help="Username (skips login dialog if provided)")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server port (default: 5555)")
    args = parser.parse_args()

    if args.username:
        ChatWindow(args.username, args.host, args.port)
        return

    login = LoginWindow()
    if login.result is None:
        sys.exit(0)

    uname, host, port = login.result
    ChatWindow(uname, host, port)


if __name__ == "__main__":
    main()
