#!/usr/bin/env python3
"""
Care Courier Web Server
A small Tkinter desktop app for serving a selected website folder on localhost or a LAN.
Uses only the Python standard library.
"""

import os
import sys
import time
import socket
import queue
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial
from urllib.parse import urlsplit


APP_NAME = "Care Courier Web Server"
DEFAULT_HOSTNAME = "care-courier.home.arpa"
DEFAULT_PORT = 8000
BG = "#0B1220"
PANEL = "#121D30"
PANEL_ALT = "#17243A"
TEXT = "#EAF2FF"
MUTED = "#9BAAC2"
TEAL = "#2DD4BF"
BLUE = "#60A5FA"
PURPLE = "#A78BFA"
GREEN = "#4ADE80"
RED = "#FB7185"
YELLOW = "#FBBF24"
LOG_BG = "#070D17"


def get_lan_ip():
    """Best-effort local IPv4 detection without sending application data."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP connect only asks the OS which interface would be used.
        sock.connect(("192.0.2.1", 80))
        address = sock.getsockname()[0]
        if address and not address.startswith("127."):
            return address
    except OSError:
        pass
    finally:
        sock.close()
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = item[4][0]
            if not address.startswith("127.") and not address.startswith("169.254."):
                return address
    except OSError:
        pass
    return "127.0.0.1"


def timestamp():
    return datetime.now().strftime("%H:%M:%S")


class CareHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class RequestHandler(SimpleHTTPRequestHandler):
    """HTTP handler that reports requests to the Tkinter thread through a queue."""

    def __init__(self, *args, directory=None, log_queue=None, **kwargs):
        self.log_queue = log_queue
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, fmt, *args):
        # SimpleHTTPRequestHandler calls this for completed requests.
        try:
            message = fmt % args
        except Exception:
            message = fmt
        status = None
        if args:
            try:
                status = int(args[1])
            except (IndexError, TypeError, ValueError):
                pass
        client = self.client_address[0] if self.client_address else "unknown"
        line = f"{timestamp()}  {client:<15}  {message}"
        if self.log_queue is not None:
            self.log_queue.put(("log", line, status))

    def log_error(self, fmt, *args):
        try:
            message = fmt % args
        except Exception:
            message = fmt
        client = self.client_address[0] if self.client_address else "unknown"
        line = f"{timestamp()}  {client:<15}  ERROR: {message}"
        if self.log_queue is not None:
            self.log_queue.put(("log", line, 400))

    def log_request(self, code="-", size="-"):
        # Include method and URL path, and the actual response code.
        try:
            status = int(code)
        except (TypeError, ValueError):
            status = None
        request_line = getattr(self, "requestline", "")
        client = self.client_address[0] if self.client_address else "unknown"
        line = f"{timestamp()}  {client:<15}  {request_line}  -> {code}"
        if size not in ("-", None):
            line += f"  ({size} bytes)"
        if self.log_queue is not None:
            self.log_queue.put(("log", line, status))


class CareCourierApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1060x820")
        self.root.minsize(780, 650)
        self.root.configure(bg=BG)

        self.log_queue = queue.Queue()
        self.httpd = None
        self.server_thread = None
        self.server_started_at = None
        self.request_count = 0
        self.error_count = 0
        self.closing = False
        self.server_state = "OFFLINE"
        self.lan_ip = get_lan_ip()

        self.folder_var = tk.StringVar(value=os.path.abspath(os.getcwd()))
        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        self.hostname_var = tk.StringVar(value=DEFAULT_HOSTNAME)
        self.lan_mode_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="OFFLINE")
        self.url_local_var = tk.StringVar(value=f"http://127.0.0.1:{DEFAULT_PORT}/")
        self.url_lan_var = tk.StringVar(value=f"http://{self.lan_ip}:{DEFAULT_PORT}/")
        self.url_hostname_var = tk.StringVar(value=f"http://{DEFAULT_HOSTNAME}:{DEFAULT_PORT}/")
        self.uptime_var = tk.StringVar(value="00:00:00")
        self.request_var = tk.StringVar(value="0")
        self.errors_var = tk.StringVar(value="0")
        self.mode_var = tk.StringVar(value="LOCALHOST ONLY")

        self._setup_style()
        self._build_ui()
        self._refresh_urls()
        self._poll_queue()
        self._tick_uptime()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TCombobox", fieldbackground=PANEL_ALT, background=PANEL_ALT,
                        foreground=TEXT, arrowcolor=TEAL)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL_ALT)],
                  foreground=[("readonly", TEXT)])
        style.configure("Horizontal.TProgressbar", troughcolor=PANEL_ALT, background=TEAL)

    def _button(self, parent, text, command, color=TEAL, fg=BG, width=None):
        opts = dict(text=text, command=command, bg=color, fg=fg, activebackground=color,
                    activeforeground=fg, relief="flat", bd=0, cursor="hand2",
                    font=("Segoe UI", 10, "bold"), padx=13, pady=9)
        if width:
            opts["width"] = width
        return tk.Button(parent, **opts)

    def _panel(self, parent, title, accent=TEAL):
        outer = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground="#24344D")
        header = tk.Frame(outer, bg=PANEL)
        header.pack(fill="x", padx=16, pady=(13, 8))
        tk.Frame(header, bg=accent, width=4, height=19).pack(side="left", padx=(0, 9))
        tk.Label(header, text=title, bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        return outer

    def _build_ui(self):
        # Scrollable page keeps the controls usable on shorter displays.
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.page = tk.Frame(self.canvas, bg=BG, padx=20, pady=16)
        self.page_window = self.canvas.create_window((0, 0), window=self.page, anchor="nw")
        self.page.bind("<Configure>", self._on_page_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        header = tk.Frame(self.page, bg=BG)
        header.pack(fill="x", pady=(0, 15))
        logo = tk.Canvas(header, width=54, height=54, bg=BG, highlightthickness=0)
        logo.pack(side="left", padx=(0, 12))
        logo.create_oval(2, 2, 52, 52, fill=TEAL, outline="")
        logo.create_text(27, 27, text="CC", fill=BG, font=("Segoe UI", 16, "bold"))
        title_frame = tk.Frame(header, bg=BG)
        title_frame.pack(side="left", fill="x", expand=True)
        tk.Label(title_frame, text=APP_NAME, bg=BG, fg=TEXT,
                 font=("Segoe UI", 20, "bold")).pack(anchor="w")
        tk.Label(title_frame, text="Local website sharing • Simple, fast, under your control",
                 bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 0))
        self.status_pill = tk.Label(header, text="● OFFLINE", bg="#3A1D2A", fg=RED,
                                    font=("Segoe UI", 10, "bold"), padx=12, pady=8)
        self.status_pill.pack(side="right", padx=(10, 0))

        # Main two-column area
        top = tk.Frame(self.page, bg=BG)
        top.pack(fill="x")
        top.columnconfigure(0, weight=3)
        top.columnconfigure(1, weight=2)

        folder_panel = self._panel(top, "WEBSITE DIRECTORY", BLUE)
        folder_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 12))
        folder_body = tk.Frame(folder_panel, bg=PANEL)
        folder_body.pack(fill="x", padx=16, pady=(0, 15))
        tk.Label(folder_body, text="Choose the folder containing your website files.",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 8))
        path_row = tk.Frame(folder_body, bg=PANEL)
        path_row.pack(fill="x")
        self.folder_entry = tk.Entry(path_row, textvariable=self.folder_var, bg=PANEL_ALT,
                                     fg=TEXT, insertbackground=TEXT, relief="flat",
                                     font=("Consolas", 9), highlightthickness=1,
                                     highlightbackground="#31415A")
        self.folder_entry.pack(side="left", fill="x", expand=True, ipady=9, padx=(0, 8))
        self._button(path_row, "Browse Folder", self.browse_folder, BLUE).pack(side="right")
        self.index_hint = tk.Label(folder_body, text="", bg=PANEL, fg=GREEN,
                                   font=("Segoe UI", 9))
        self.index_hint.pack(anchor="w", pady=(8, 0))

        config_panel = self._panel(top, "SERVER CONFIGURATION", PURPLE)
        config_panel.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 12))
        config_body = tk.Frame(config_panel, bg=PANEL)
        config_body.pack(fill="x", padx=16, pady=(0, 15))
        tk.Label(config_body, text="Port", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w")
        self.port_entry = tk.Entry(config_body, textvariable=self.port_var, width=9,
                                   bg=PANEL_ALT, fg=TEXT, insertbackground=TEXT,
                                   relief="flat", font=("Segoe UI", 10),
                                   highlightthickness=1, highlightbackground="#31415A")
        self.port_entry.grid(row=1, column=0, sticky="w", ipady=7, pady=(5, 12))
        tk.Label(config_body, text="Custom hostname", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 9, "bold")).grid(row=2, column=0, sticky="w")
        self.hostname_entry = tk.Entry(config_body, textvariable=self.hostname_var,
                                       bg=PANEL_ALT, fg=TEXT, insertbackground=TEXT,
                                       relief="flat", font=("Segoe UI", 10),
                                       highlightthickness=1, highlightbackground="#31415A")
        self.hostname_entry.grid(row=3, column=0, sticky="ew", ipady=7, pady=(5, 10))
        config_body.columnconfigure(0, weight=1)
        self.lan_check = tk.Checkbutton(
            config_body, text="Enable LAN access (other devices on your network)",
            variable=self.lan_mode_var, command=self.on_lan_toggle,
            bg=PANEL, fg=YELLOW, selectcolor=PANEL_ALT, activebackground=PANEL,
            activeforeground=YELLOW, font=("Segoe UI", 9, "bold"), wraplength=280,
            justify="left"
        )
        self.lan_check.grid(row=4, column=0, sticky="w", pady=(0, 5))
        tk.Label(config_body, text="Off by default for safer localhost-only access.",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).grid(row=5, column=0, sticky="w")

        controls = self._panel(self.page, "SERVER CONTROLS", TEAL)
        controls.pack(fill="x", pady=(0, 12))
        control_row = tk.Frame(controls, bg=PANEL)
        control_row.pack(fill="x", padx=16, pady=(0, 15))
        self.start_btn = self._button(control_row, "▶  Start Server", self.start_server, GREEN)
        self.start_btn.pack(side="left", padx=(0, 8))
        self.stop_btn = self._button(control_row, "■  Stop Server", self.stop_server, RED, "#230B12")
        self.stop_btn.pack(side="left", padx=(0, 8))
        self.stop_btn.configure(state="disabled")
        self._button(control_row, "Open Website", self.open_website, BLUE).pack(side="left", padx=(0, 8))
        self._button(control_row, "LAN Setup", self.show_lan_setup, PURPLE, "#160D2C").pack(side="left")

        urls = self._panel(self.page, "ACCESS URLS", BLUE)
        urls.pack(fill="x", pady=(0, 12))
        url_body = tk.Frame(urls, bg=PANEL)
        url_body.pack(fill="x", padx=16, pady=(0, 15))
        self._url_row(url_body, "LOCAL", self.url_local_var, self.copy_local, BLUE)
        self._url_row(url_body, "LAN IP", self.url_lan_var, self.copy_lan, TEAL)
        self._url_row(url_body, "HOSTNAME", self.url_hostname_var, self.copy_hostname, PURPLE)
        tk.Label(url_body,
                 text="LAN/hostname URLs work only when the server is running and network/DNS settings allow access. This does not publish your site to the internet.",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 8), wraplength=900,
                 justify="left").pack(anchor="w", pady=(7, 0))

        stats = tk.Frame(self.page, bg=BG)
        stats.pack(fill="x", pady=(0, 12))
        for col in range(3):
            stats.columnconfigure(col, weight=1)
        self._stat_card(stats, 0, "REQUESTS", self.request_var, TEAL)
        self._stat_card(stats, 1, "ERROR RESPONSES", self.errors_var, RED)
        self._stat_card(stats, 2, "UPTIME", self.uptime_var, PURPLE)

        logs_panel = self._panel(self.page, "LIVE SERVER LOGS", GREEN)
        logs_panel.pack(fill="both", expand=True, pady=(0, 12))
        logs_toolbar = tk.Frame(logs_panel, bg=PANEL)
        logs_toolbar.pack(fill="x", padx=16, pady=(0, 8))
        tk.Label(logs_toolbar, text="TIMESTAMP   CLIENT IP        REQUEST / RESPONSE",
                 bg=PANEL, fg=MUTED, font=("Consolas", 8, "bold")).pack(side="left")
        self._button(logs_toolbar, "Clear Logs", self.clear_logs, PANEL_ALT, TEXT).pack(side="right")
        log_frame = tk.Frame(logs_panel, bg=LOG_BG)
        log_frame.pack(fill="both", expand=True, padx=16, pady=(0, 15))
        self.log_text = tk.Text(log_frame, height=12, bg=LOG_BG, fg="#B9FBC0",
                                insertbackground=TEXT, relief="flat", wrap="none",
                                font=("Consolas", 9), padx=10, pady=10,
                                state="disabled")
        log_scroll_y = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll_x = ttk.Scrollbar(log_frame, orient="horizontal", command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=log_scroll_y.set, xscrollcommand=log_scroll_x.set)
        log_scroll_y.pack(side="right", fill="y")
        log_scroll_x.pack(side="bottom", fill="x")
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_text.tag_configure("error", foreground=RED)
        self.log_text.tag_configure("success", foreground="#86EFAC")
        self.log_text.tag_configure("normal", foreground="#B9FBC0")

        footer = tk.Label(self.page,
                          text="Built-in Python HTTP server • Intended for local development and trusted LAN file sharing, not production hosting.",
                          bg=BG, fg=MUTED, font=("Segoe UI", 8), wraplength=950, justify="left")
        footer.pack(fill="x", pady=(0, 6))
        self._append_log("Ready. Select a website folder, check the port, then start the server.", "normal")
        self._update_index_hint()

    def _url_row(self, parent, label, variable, copy_command, color):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=4)
        tk.Label(row, text=label, width=9, anchor="w", bg=PANEL, fg=color,
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        entry = tk.Entry(row, textvariable=variable, bg=PANEL_ALT, fg=TEXT,
                         insertbackground=TEXT, relief="flat", font=("Consolas", 9),
                         state="readonly", readonlybackground=PANEL_ALT,
                         highlightthickness=1, highlightbackground="#263852")
        entry.pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 8))
        self._button(row, "Copy", copy_command, color, BG, width=7).pack(side="right")

    def _stat_card(self, parent, column, label, variable, accent):
        card = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground="#24344D")
        card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 6, 6 if column < 2 else 0))
        tk.Label(card, text=label, bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=14, pady=(10, 2))
        tk.Label(card, textvariable=variable, bg=PANEL, fg=accent,
                 font=("Consolas", 17, "bold")).pack(anchor="w", padx=14, pady=(0, 10))

    def _on_page_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.page_window, width=event.width)

    def _on_mousewheel(self, event):
        try:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except (tk.TclError, AttributeError):
            pass

    def _append_log(self, message, tag="normal"):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n", tag)
        self.log_text.see("end")
        # Keep memory bounded for long sessions.
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > 1500:
            self.log_text.delete("1.0", "300.0")
        self.log_text.configure(state="disabled")

    def clear_logs(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self._append_log("Logs cleared.", "normal")

    def browse_folder(self):
        chosen = filedialog.askdirectory(title="Select website folder",
                                         initialdir=self.folder_var.get() or os.getcwd())
        if chosen:
            self.folder_var.set(os.path.abspath(chosen))
            self._update_index_hint()

    def _update_index_hint(self):
        folder = os.path.abspath(os.path.expanduser(self.folder_var.get().strip() or "."))
        if os.path.isdir(folder):
            if os.path.isfile(os.path.join(folder, "index.html")):
                text, color = "✓ index.html found — it will be served at the root URL.", GREEN
            else:
                text, color = "No index.html found — directory listing may be shown.", YELLOW
        else:
            text, color = "Folder does not exist. Choose a valid website directory.", RED
        self.index_hint.configure(text=text, fg=color)

    def on_lan_toggle(self):
        if self.lan_mode_var.get():
            answer = messagebox.askyesno(
                "Enable LAN access?",
                "LAN mode binds to 0.0.0.0, allowing other devices on your local network to connect.\n\n"
                "Only share a folder intended for others to read. Your firewall may need an inbound rule.\n\nEnable LAN access?",
                icon="warning"
            )
            if not answer:
                self.lan_mode_var.set(False)
        self.mode_var.set("LAN ACCESS" if self.lan_mode_var.get() else "LOCALHOST ONLY")
        self._refresh_urls()

    def _get_port(self):
        try:
            port = int(self.port_var.get().strip())
        except ValueError:
            raise ValueError("Port must be a whole number between 1 and 65535.")
        if not 1 <= port <= 65535:
            raise ValueError("Port must be between 1 and 65535.")
        return port

    def _get_hostname(self):
        hostname = self.hostname_var.get().strip().lower().rstrip(".")
        if not hostname:
            raise ValueError("Enter a hostname, for example care-courier.home.arpa.")
        if any(ch.isspace() for ch in hostname) or "/" in hostname or ":" in hostname:
            raise ValueError("Hostname must contain only a hostname, without spaces or URL paths.")
        if len(hostname) > 253 or any(not part or len(part) > 63 for part in hostname.split(".")):
            raise ValueError("Enter a valid hostname.")
        allowed = "abcdefghijklmnopqrstuvwxyz0123456789-."
        if any(ch not in allowed for ch in hostname):
            raise ValueError("Use letters, numbers, hyphens, and dots in the hostname.")
        return hostname

    def _refresh_urls(self):
        try:
            port = self._get_port()
        except ValueError:
            port = DEFAULT_PORT
        try:
            hostname = self._get_hostname()
        except ValueError:
            hostname = DEFAULT_HOSTNAME
        self.lan_ip = get_lan_ip()
        self.url_local_var.set(f"http://127.0.0.1:{port}/")
        self.url_lan_var.set(f"http://{self.lan_ip}:{port}/")
        self.url_hostname_var.set(f"http://{hostname}:{port}/")

    def _copy(self, value, label):
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.root.update_idletasks()
        self._append_log(f"{timestamp()}  Copied {label}: {value}", "normal")

    def copy_local(self):
        self._refresh_urls()
        self._copy(self.url_local_var.get(), "local URL")

    def copy_lan(self):
        self._refresh_urls()
        self._copy(self.url_lan_var.get(), "LAN URL")

    def copy_hostname(self):
        self._refresh_urls()
        self._copy(self.url_hostname_var.get(), "hostname URL")

    def open_website(self):
        self._refresh_urls()
        if self.server_state != "RUNNING":
            messagebox.showinfo("Server is offline", "Start the server before opening the website.")
            return
        url = self.url_local_var.get()
        if self.lan_mode_var.get():
            url = self.url_lan_var.get()
        try:
            webbrowser.open(url)
        except Exception as exc:
            messagebox.showerror("Could not open browser", str(exc))

    def start_server(self):
        if self.server_state in ("RUNNING", "STARTING", "STOPPING"):
            return
        folder = os.path.abspath(os.path.expanduser(self.folder_var.get().strip()))
        if not os.path.isdir(folder):
            messagebox.showerror("Invalid website folder", "Choose a folder that exists before starting the server.")
            self._update_index_hint()
            return
        try:
            port = self._get_port()
            hostname = self._get_hostname()
        except ValueError as exc:
            messagebox.showerror("Check server settings", str(exc))
            return
        bind_host = "0.0.0.0" if self.lan_mode_var.get() else "127.0.0.1"
        self._refresh_urls()
        if self.lan_mode_var.get():
            if not messagebox.askyesno(
                "Confirm LAN server",
                f"The server will listen on all IPv4 interfaces at port {port}.\n\n"
                f"LAN URL: http://{self.lan_ip}:{port}/\n\n"
                "Continue only if the selected folder is safe to share with trusted devices.",
                icon="warning"
            ):
                return
        self.server_state = "STARTING"
        self.status_var.set("STARTING")
        self.status_pill.configure(text="● STARTING", bg="#3A3020", fg=YELLOW)
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._set_settings_state("disabled")
        self._append_log(f"{timestamp()}  Starting server on {bind_host}:{port} serving {folder}", "normal")

        handler = partial(RequestHandler, directory=folder, log_queue=self.log_queue)
        try:
            self.httpd = CareHTTPServer((bind_host, port), handler)
        except OSError as exc:
            self.httpd = None
            self.server_state = "OFFLINE"
            self.status_var.set("OFFLINE")
            self.status_pill.configure(text="● OFFLINE", bg="#3A1D2A", fg=RED)
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            self._set_settings_state("normal")
            self._append_log(f"{timestamp()}  SERVER ERROR: {exc}", "error")
            if getattr(exc, "errno", None) in (98, 48, 10048):
                detail = f"Port {port} is already in use. Close the other app or choose another port."
            else:
                detail = str(exc)
            messagebox.showerror("Could not start server", detail)
            return

        self.server_started_at = time.time()
        self.server_state = "RUNNING"
        self.status_var.set("RUNNING")
        self.status_pill.configure(text="● RUNNING", bg="#12392F", fg=GREEN)
        self._append_log(f"{timestamp()}  Server running. Local URL: {self.url_local_var.get()}", "success")
        if self.lan_mode_var.get():
            self._append_log(f"{timestamp()}  LAN URL: {self.url_lan_var.get()}", "success")
        self._append_log(f"{timestamp()}  Hostname URL (requires local DNS/hosts setup): {self.url_hostname_var.get()}", "normal")
        self.server_thread = threading.Thread(target=self._serve, name="CareCourierHTTP", daemon=True)
        self.server_thread.start()

    def _serve(self):
        try:
            self.httpd.serve_forever(poll_interval=0.25)
        except Exception as exc:
            self.log_queue.put(("log", f"{timestamp()}  SERVER THREAD ERROR: {exc}", 500))
            self.log_queue.put(("server_error", str(exc), None))

    def stop_server(self):
        if self.server_state != "RUNNING" or self.httpd is None:
            return
        self.server_state = "STOPPING"
        self.status_pill.configure(text="● STOPPING", bg="#3A3020", fg=YELLOW)
        self.stop_btn.configure(state="disabled")
        self._append_log(f"{timestamp()}  Stopping server...", "normal")
        server = self.httpd

        def shutdown():
            try:
                server.shutdown()
                server.server_close()
                self.log_queue.put(("stopped", "Server stopped and socket closed.", None))
            except Exception as exc:
                self.log_queue.put(("log", f"{timestamp()}  Shutdown error: {exc}", 500))
                self.log_queue.put(("stopped", "Server stopped with a shutdown warning.", None))
        threading.Thread(target=shutdown, name="CareCourierShutdown", daemon=True).start()

    def _finish_stop(self, message="Server stopped."):
        self.httpd = None
        self.server_thread = None
        self.server_started_at = None
        self.server_state = "OFFLINE"
        self.status_var.set("OFFLINE")
        self.status_pill.configure(text="● OFFLINE", bg="#3A1D2A", fg=RED)
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self._set_settings_state("normal")
        self.uptime_var.set("00:00:00")
        self._append_log(f"{timestamp()}  {message}", "normal")

    def _set_settings_state(self, state):
        self.folder_entry.configure(state=state)
        self.port_entry.configure(state=state)
        self.hostname_entry.configure(state=state)
        self.lan_check.configure(state=state)

    def _poll_queue(self):
        if self.closing:
            return
        try:
            while True:
                item = self.log_queue.get_nowait()
                kind, message, status = item
                if kind == "log":
                    tag = "error" if (status is not None and status >= 400) or "ERROR" in message else "success"
                    self._append_log(message, tag)
                    if status is not None:
                        self.request_count += 1
                        if status >= 400:
                            self.error_count += 1
                        self.request_var.set(str(self.request_count))
                        self.errors_var.set(str(self.error_count))
                elif kind == "stopped":
                    self._finish_stop(message)
                elif kind == "server_error":
                    self._append_log(f"Server thread error: {message}", "error")
                    self._finish_stop("Server stopped after an unexpected error.")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _tick_uptime(self):
        if self.closing:
            return
        if self.server_state == "RUNNING" and self.server_started_at:
            seconds = max(0, int(time.time() - self.server_started_at))
            h, rem = divmod(seconds, 3600)
            m, s = divmod(rem, 60)
            self.uptime_var.set(f"{h:02d}:{m:02d}:{s:02d}")
        self.root.after(1000, self._tick_uptime)

    def show_lan_setup(self):
        self._refresh_urls()
        hostname = self._get_hostname()
        win = tk.Toplevel(self.root)
        win.title("LAN Setup — Care Courier Web Server")
        win.configure(bg=BG)
        win.geometry("720x530")
        win.minsize(600, 460)
        win.transient(self.root)
        win.grab_set()

        tk.Label(win, text="LAN SETUP", bg=BG, fg=TEAL,
                 font=("Segoe UI", 18, "bold")).pack(anchor="w", padx=22, pady=(20, 4))
        tk.Label(win, text="Use this guide to let other computers on the same local network reach your site.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 10), wraplength=670,
                 justify="left").pack(anchor="w", padx=22, pady=(0, 14))

        info = tk.Frame(win, bg=PANEL, highlightthickness=1, highlightbackground="#24344D")
        info.pack(fill="x", padx=22, pady=(0, 12))
        tk.Label(info, text=f"LAN IP:  {self.lan_ip}", bg=PANEL, fg=TEXT,
                 font=("Consolas", 11, "bold")).pack(anchor="w", padx=14, pady=(12, 4))
        tk.Label(info, text=f"Hostname:  {hostname}", bg=PANEL, fg=TEXT,
                 font=("Consolas", 11, "bold")).pack(anchor="w", padx=14, pady=(0, 4))
        tk.Label(info, text=f"Hostname URL:  {self.url_hostname_var.get()}", bg=PANEL, fg=PURPLE,
                 font=("Consolas", 10)).pack(anchor="w", padx=14, pady=(0, 12))

        tk.Label(win, text="Hosts-file entry (add on each client PC)", bg=BG, fg=TEXT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=22)
        entry_text = f"{self.lan_ip}    {hostname}"
        text_box = tk.Text(win, height=2, bg=LOG_BG, fg="#B9FBC0", relief="flat",
                           font=("Consolas", 11), padx=10, pady=8)
        text_box.pack(fill="x", padx=22, pady=(6, 6))
        text_box.insert("1.0", entry_text)
        text_box.configure(state="disabled")
        self._button(win, "Copy Hosts Entry", lambda: self._copy(entry_text, "hosts entry"), TEAL).pack(anchor="e", padx=22, pady=(0, 10))

        instructions = (
            "Client hosts-file locations:\n"
            "• Windows: C:\\Windows\\System32\\drivers\\etc\\hosts (edit as Administrator)\n"
            "• Linux/macOS: /etc/hosts (edit with administrator privileges)\n\n"
            "Then open the Hostname URL above. Add the entry on every client; this app does not edit hosts files or configure DNS automatically.\n\n"
            "Firewall: allow inbound TCP traffic on your chosen port (default 8000) on the host computer, preferably only on a trusted Private/Home network. "
            "Do not create a router port-forward unless you deliberately intend public exposure."
        )
        tk.Label(win, text=instructions, bg=BG, fg=MUTED, font=("Segoe UI", 9),
                 justify="left", wraplength=670).pack(fill="x", padx=22, pady=(0, 14))
        self._button(win, "Close", win.destroy, PURPLE, "#160D2C").pack(anchor="e", padx=22, pady=(0, 18))

    def on_close(self):
        if self.closing:
            return
        if self.httpd is None:
            self.closing = True
            self.root.destroy()
            return
        if not messagebox.askyesno("Exit application", "The server is running. Stop it and close the application?"):
            return
        self.closing = True
        server = self.httpd
        self._append_log("Application closing; stopping server...")
        def cleanup():
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
            try:
                self.root.after(0, self.root.destroy)
            except tk.TclError:
                pass
        threading.Thread(target=cleanup, name="CareCourierExit", daemon=True).start()


def main():
    root = tk.Tk()
    app = CareCourierApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
