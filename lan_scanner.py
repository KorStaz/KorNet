from __future__ import annotations

import csv
import ipaddress
import json
import os
import queue
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    import psutil
except ImportError:
    psutil = None

APP_NAME = "KorNet"
COMMON_PORTS = [21, 22, 23, 25, 53, 80, 110, 139, 143, 443, 445, 3389, 8080]
MAX_HOSTS = 1024
DEFAULT_SETTINGS = {
    "refresh_interval": 3,
    "auto_refresh": True,
    "hide_localhost": False,
    "hide_private": False,
    "socket_timeout": 0.35,
    "max_concurrency": 64,
    "export_directory": str(Path.home() / "Documents"),
    "theme": "dark",
}

def app_data_dir() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home()))
    folder = base / APP_NAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder

def local_ipv4() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return "Unavailable"
    finally:
        sock.close()

def detected_network() -> str:
    ip = local_ipv4()
    try:
        addr = ipaddress.ip_address(ip)
        if addr.version == 4 and addr.is_private:
            return ".".join(ip.split(".")[:3]) + ".0/24"
    except ValueError:
        pass
    return "192.168.1.0/24"

def safe_remote(conn) -> tuple[str, str]:
    try:
        return (conn.raddr.ip, str(conn.raddr.port)) if conn.raddr else ("", "")
    except (AttributeError, OSError):
        return "", ""

def safe_local(conn) -> tuple[str, str]:
    try:
        return (conn.laddr.ip, str(conn.laddr.port)) if conn.laddr else ("", "")
    except (AttributeError, OSError):
        return "", ""

class KorNetApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("KorNet — Network Monitor")
        self.root.geometry("1280x790")
        self.root.minsize(980, 620)
        self.root.configure(bg="#101722")
        self._set_window_icon()
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.scan_thread = None
        self.monitor_thread = None
        self.closing = False
        self.connections = []
        self.peers = {}
        self.peer_history = []
        self.scan_rows = []
        self.scan_status = "Idle"
        self.scan_progress = tk.StringVar(value="No scan running")
        self.settings_path = app_data_dir() / "settings.json"
        self.settings = self.load_settings()
        self._build_style()
        self._build_shell()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(150, self.drain_events)
        if self.settings.get("auto_refresh", True):
            self.start_monitor()
        else:
            self.refresh_connections()

    def _resource_path(self, relative_path: str) -> Path:
        # PyInstaller extracts bundled resources to sys._MEIPASS.
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        return base / relative_path

    def _set_window_icon(self):
        try:
            icon_file = self._resource_path("assets/kornet.ico")
            if icon_file.exists():
                self.root.iconbitmap(default=str(icon_file))
        except (OSError, tk.TclError):
            pass

    def load_settings(self):
        data = dict(DEFAULT_SETTINGS)
        try:
            data.update(json.loads(self.settings_path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            pass
        return data

    def save_settings(self):
        try:
            self.settings_path.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
            self.status_var.set("Settings saved")
        except OSError as exc:
            messagebox.showerror("Settings", f"Could not save settings:\n{exc}")

    def _build_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        bg, panel, fg, muted, accent = "#101722", "#182333", "#e7edf5", "#9aabba", "#36a3d9"
        style.configure(".", background=bg, foreground=fg, fieldbackground=panel, bordercolor="#304156",
                        font=("Segoe UI", 9))
        style.configure("TFrame", background=bg)
        style.configure("Panel.TFrame", background=panel)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("Muted.TLabel", background=bg, foreground=muted)
        style.configure("Title.TLabel", background=bg, foreground=fg, font=("Segoe UI Semibold", 18))
        style.configure("Metric.TLabel", background=panel, foreground="#ffffff", font=("Segoe UI Semibold", 22))
        style.configure("MetricName.TLabel", background=panel, foreground=muted, font=("Segoe UI", 9))
        style.configure("TButton", background="#26374c", foreground=fg, padding=(10, 6), borderwidth=0)
        style.map("TButton", background=[("active", "#34506b"), ("disabled", "#202a36")])
        style.configure("Accent.TButton", background=accent, foreground="#07121c")
        style.map("Accent.TButton", background=[("active", "#65bee8")])
        style.configure("TEntry", fieldbackground="#0d1520", foreground=fg, insertcolor=fg)
        style.configure("TCombobox", fieldbackground="#0d1520", foreground=fg)
        style.configure("Treeview", background="#111c29", fieldbackground="#111c29", foreground=fg,
                        rowheight=25, borderwidth=0)
        style.configure("Treeview.Heading", background="#26374c", foreground=fg, padding=6)
        style.map("Treeview", background=[("selected", "#245477")])
        style.configure("TNotebook", background=bg, borderwidth=0)
        style.configure("TNotebook.Tab", background=panel, foreground=fg, padding=(12, 7))
        style.map("TNotebook.Tab", background=[("selected", "#26374c")])

    def _build_shell(self):
        header = ttk.Frame(self.root, padding=(18, 14))
        header.pack(fill="x")
        ttk.Label(header, text="KORNET", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="NETWORK VISIBILITY  /  WINDOWS", style="Muted.TLabel").pack(side="left", padx=16)
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(header, textvariable=self.status_var, style="Muted.TLabel").pack(side="right")

        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self.dashboard = ttk.Frame(self.tabs, padding=14)
        self.monitor_page = ttk.Frame(self.tabs, padding=10)
        self.peers_page = ttk.Frame(self.tabs, padding=10)
        self.scanner_page = ttk.Frame(self.tabs, padding=10)
        self.settings_page = ttk.Frame(self.tabs, padding=14)
        for page, label in [(self.dashboard, "Dashboard"), (self.monitor_page, "P2P Connection Monitor"),
                            (self.peers_page, "Direct P2P Peer Detection"), (self.scanner_page, "LAN Scanner"),
                            (self.settings_page, "Settings")]:
            self.tabs.add(page, text=label)
        self._build_dashboard()
        self._build_monitor()
        self._build_peers()
        self._build_scanner()
        self._build_settings()

    def _metric(self, parent, title, variable):
        card = ttk.Frame(parent, style="Panel.TFrame", padding=14)
        ttk.Label(card, text=title, style="MetricName.TLabel").pack(anchor="w")
        ttk.Label(card, textvariable=variable, style="Metric.TLabel").pack(anchor="w", pady=(7, 0))
        return card

    def _build_dashboard(self):
        ttk.Label(self.dashboard, text="Network overview", style="Title.TLabel").pack(anchor="w", pady=(0, 14))
        row = ttk.Frame(self.dashboard)
        row.pack(fill="x")
        self.metric_total = tk.StringVar(value="—")
        self.metric_est = tk.StringVar(value="—")
        self.metric_peers = tk.StringVar(value="—")
        self.metric_listen = tk.StringVar(value="—")
        for title, var in [("TOTAL CONNECTIONS", self.metric_total), ("ESTABLISHED TCP", self.metric_est),
                           ("OBSERVED PEERS", self.metric_peers), ("LISTENING SOCKETS", self.metric_listen)]:
            self._metric(row, title, var).pack(side="left", fill="both", expand=True, padx=(0, 10))
        info = ttk.Frame(self.dashboard, style="Panel.TFrame", padding=16)
        info.pack(fill="x", pady=18)
        ttk.Label(info, text="LOCAL NETWORK", style="MetricName.TLabel").pack(anchor="w")
        self.local_ip_var = tk.StringVar(value=local_ipv4())
        ttk.Label(info, textvariable=self.local_ip_var, style="Metric.TLabel").pack(anchor="w", pady=6)
        self.dash_scan_var = tk.StringVar(value="LAN scanning: Idle")
        ttk.Label(info, textvariable=self.dash_scan_var).pack(anchor="w")
        ttk.Label(self.dashboard, text="KorNet reports socket information visible to this computer. VPNs, NAT, relays and firewalls can affect what is visible.",
                  style="Muted.TLabel", wraplength=1050).pack(anchor="w", pady=10)
        ttk.Button(self.dashboard, text="Refresh connections now", command=self.refresh_connections).pack(anchor="w")

    def _make_tree(self, parent, columns, headings=None, height=16):
        wrap = ttk.Frame(parent)
        wrap.pack(fill="both", expand=True, pady=(8, 0))
        tree = ttk.Treeview(wrap, columns=columns, show="headings", height=height)
        for col in columns:
            tree.heading(col, text=(headings or {}).get(col, col.replace("_", " ").title()))
            tree.column(col, width=120, minwidth=70, stretch=True)
        y = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        x = ttk.Scrollbar(wrap, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y.grid(row=0, column=1, sticky="ns")
        x.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        return tree

    def _build_monitor(self):
        ttk.Label(self.monitor_page, text="Live socket table", style="Title.TLabel").pack(anchor="w")
        bar = ttk.Frame(self.monitor_page)
        bar.pack(fill="x", pady=8)
        ttk.Label(bar, text="Search").pack(side="left")
        self.search_var = tk.StringVar()
        search = ttk.Entry(bar, textvariable=self.search_var, width=24)
        search.pack(side="left", padx=6)
        search.bind("<KeyRelease>", lambda _e: self.render_connections())
        self.hide_local_var = tk.BooleanVar(value=self.settings.get("hide_localhost", False))
        self.hide_private_var = tk.BooleanVar(value=self.settings.get("hide_private", False))
        ttk.Checkbutton(bar, text="Hide localhost", variable=self.hide_local_var,
                        command=self.render_connections).pack(side="left", padx=5)
        ttk.Checkbutton(bar, text="Hide private LAN", variable=self.hide_private_var,
                        command=self.render_connections).pack(side="left", padx=5)
        ttk.Button(bar, text="Refresh", command=self.refresh_connections).pack(side="right")
        ttk.Button(bar, text="Export CSV", command=lambda: self.export_rows(self.filtered_connections(), "connections")).pack(side="right", padx=6)
        self.conn_count_var = tk.StringVar(value="0 connections")
        ttk.Label(self.monitor_page, textvariable=self.conn_count_var, style="Muted.TLabel").pack(anchor="w")
        self.conn_tree = self._make_tree(self.monitor_page,
            ("remote_ip", "remote_port", "local_ip", "local_port", "protocol", "state", "pid", "process", "direction"),
            {"remote_ip":"Remote IP","remote_port":"Remote Port","local_ip":"Local IP","local_port":"Local Port",
             "protocol":"Protocol","state":"State","pid":"PID","process":"Process","direction":"Direction"})

    def _build_peers(self):
        ttk.Label(self.peers_page, text="Observed remote endpoints", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self.peers_page, text="First/last seen values are based on observations made while KorNet is running.",
                  style="Muted.TLabel").pack(anchor="w", pady=(4, 8))
        bar = ttk.Frame(self.peers_page)
        bar.pack(fill="x")
        ttk.Button(bar, text="Refresh", command=self.refresh_connections).pack(side="left")
        ttk.Button(bar, text="Export CSV", command=lambda: self.export_rows(self.peer_export_rows(), "peers")).pack(side="right")
        self.peer_count_var = tk.StringVar(value="0 currently observed")
        ttk.Label(bar, textvariable=self.peer_count_var, style="Muted.TLabel").pack(side="left", padx=12)
        self.peer_tree = self._make_tree(self.peers_page,
            ("classification","remote_ip","remote_port","local_ip","local_port","protocol","state","pid","process","first_seen","last_seen","duration","direction"),
            {"classification":"Classification","remote_ip":"Remote IP","remote_port":"Remote Port","local_ip":"Local IP",
             "local_port":"Local Port","protocol":"Protocol","state":"State","pid":"PID","process":"Process",
             "first_seen":"First Seen","last_seen":"Last Seen","duration":"Observed Duration","direction":"Direction"})

    def _build_scanner(self):
        ttk.Label(self.scanner_page, text="Private IPv4 LAN scanner", style="Title.TLabel").pack(anchor="w")
        controls = ttk.Frame(self.scanner_page)
        controls.pack(fill="x", pady=8)
        ttk.Label(controls, text="Network (CIDR)").grid(row=0, column=0, sticky="w")
        self.network_var = tk.StringVar(value=detected_network())
        ttk.Entry(controls, textvariable=self.network_var, width=22).grid(row=0, column=1, padx=6)
        ttk.Label(controls, text="TCP port").grid(row=0, column=2, padx=(12, 0))
        self.port_var = tk.StringVar(value="80")
        ttk.Entry(controls, textvariable=self.port_var, width=8).grid(row=0, column=3, padx=6)
        ttk.Button(controls, text="Find IPs on port", style="Accent.TButton", command=self.scan_custom).grid(row=0, column=4, padx=4)
        ttk.Button(controls, text="Scan common ports", command=self.scan_common).grid(row=0, column=5, padx=4)
        ttk.Button(controls, text="Scan all ports", command=self.scan_all).grid(row=0, column=6, padx=4)
        ttk.Button(controls, text="Stop", command=self.stop_scan).grid(row=0, column=7, padx=4)
        ttk.Label(controls, text="Only private IPv4 ranges, max 1,024 addresses. Scan only networks you own or are authorised to test.",
                  style="Muted.TLabel").grid(row=1, column=0, columnspan=8, sticky="w", pady=8)
        progressrow = ttk.Frame(self.scanner_page)
        progressrow.pack(fill="x")
        ttk.Label(progressrow, textvariable=self.scan_progress).pack(side="left")
        self.scan_bar = ttk.Progressbar(progressrow, mode="determinate")
        self.scan_bar.pack(side="right", fill="x", expand=True, padx=(12, 0))
        actions = ttk.Frame(self.scanner_page)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(actions, text="Export scan CSV", command=lambda: self.export_rows(self.scan_rows, "lan_scan")).pack(side="right")
        self.scan_tree = self._make_tree(self.scanner_page, ("ip","port","protocol","status","response"),
                                         {"ip":"IP Address","port":"Open Port","protocol":"Protocol","status":"Scan Status","response":"Response"})

    def _build_settings(self):
        ttk.Label(self.settings_page, text="Application settings", style="Title.TLabel").pack(anchor="w", pady=(0, 14))
        form = ttk.Frame(self.settings_page)
        form.pack(anchor="nw", fill="x")
        self.interval_var = tk.StringVar(value=str(self.settings.get("refresh_interval", 3)))
        self.auto_var = tk.BooleanVar(value=self.settings.get("auto_refresh", True))
        self.timeout_var = tk.StringVar(value=str(self.settings.get("socket_timeout", 0.35)))
        self.concurrency_var = tk.StringVar(value=str(self.settings.get("max_concurrency", 64)))
        self.export_var = tk.StringVar(value=self.settings.get("export_directory", str(Path.home() / "Documents")))
        ttk.Label(form, text="Refresh interval (1–60 seconds)").grid(row=0, column=0, sticky="w", pady=8)
        ttk.Entry(form, textvariable=self.interval_var, width=12).grid(row=0, column=1, sticky="w", padx=12)
        ttk.Checkbutton(form, text="Enable automatic connection refresh", variable=self.auto_var).grid(row=1, column=0, columnspan=2, sticky="w", pady=8)
        ttk.Label(form, text="Default TCP socket timeout (0.1–5 seconds)").grid(row=2, column=0, sticky="w", pady=8)
        ttk.Entry(form, textvariable=self.timeout_var, width=12).grid(row=2, column=1, sticky="w", padx=12)
        ttk.Label(form, text="Maximum scan concurrency (1–256)").grid(row=3, column=0, sticky="w", pady=8)
        ttk.Entry(form, textvariable=self.concurrency_var, width=12).grid(row=3, column=1, sticky="w", padx=12)
        ttk.Label(form, text="Export directory").grid(row=4, column=0, sticky="w", pady=8)
        ttk.Entry(form, textvariable=self.export_var, width=54).grid(row=4, column=1, sticky="w", padx=12)
        ttk.Button(form, text="Browse", command=self.choose_export_dir).grid(row=4, column=2, padx=5)
        ttk.Label(form, text="Theme: Dark (current)", style="Muted.TLabel").grid(row=5, column=0, sticky="w", pady=8)
        ttk.Button(form, text="Save and apply settings", style="Accent.TButton", command=self.apply_settings).grid(row=6, column=0, sticky="w", pady=16)
        ttk.Label(self.settings_page, text="Connection visibility depends on Windows permissions. Running as administrator may expose more process/socket metadata; KorNet does not bypass access controls.",
                  style="Muted.TLabel", wraplength=900).pack(anchor="w", pady=10)

    def choose_export_dir(self):
        selected = filedialog.askdirectory(initialdir=self.export_var.get() or str(Path.home()))
        if selected:
            self.export_var.set(selected)

    def apply_settings(self):
        try:
            interval = int(self.interval_var.get())
            timeout = float(self.timeout_var.get())
            concurrency = int(self.concurrency_var.get())
            directory = Path(self.export_var.get()).expanduser()
            if not 1 <= interval <= 60: raise ValueError("Refresh interval must be 1–60 seconds.")
            if not 0.1 <= timeout <= 5: raise ValueError("Socket timeout must be between 0.1 and 5 seconds.")
            if not 1 <= concurrency <= 256: raise ValueError("Concurrency must be 1–256.")
            directory.mkdir(parents=True, exist_ok=True)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return
        self.settings.update(refresh_interval=interval, auto_refresh=self.auto_var.get(),
                             socket_timeout=timeout, max_concurrency=concurrency,
                             export_directory=str(directory), hide_localhost=self.hide_local_var.get(),
                             hide_private=self.hide_private_var.get())
        self.save_settings()
        if self.settings["auto_refresh"]:
            self.start_monitor()
        else:
            self.stop_event.set()
            self.monitor_thread = None

    def start_monitor(self):
        if psutil is None:
            self.status_var.set("Install psutil to enable connection monitoring")
            return
        if self.monitor_thread and self.monitor_thread.is_alive():
            return
        self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self.monitor_thread.start()

    def monitor_loop(self):
        while not self.closing and self.settings.get("auto_refresh", True):
            self.collect_connections()
            interval = max(1, min(60, int(self.settings.get("refresh_interval", 3))))
            for _ in range(interval * 10):
                if self.closing or not self.settings.get("auto_refresh", True):
                    break
                time.sleep(0.1)

    def refresh_connections(self):
        if psutil is None:
            self.status_var.set("psutil is not installed")
            return
        threading.Thread(target=self.collect_connections, daemon=True).start()

    def collect_connections(self):
        try:
            raw = psutil.net_connections(kind="inet")
        except (psutil.AccessDenied, OSError) as exc:
            self.events.put(("error", f"Connection access limited: {exc}"))
            return
        local_addresses = set()
        try:
            for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                local_addresses.add(item[4][0])
        except OSError:
            pass
        local_addresses.add("127.0.0.1")
        now = datetime.now()
        stamp = now.strftime("%Y-%m-%d %H:%M:%S")
        records, observed = [], {}
        listening_endpoints = set()
        for item in raw:
            try:
                if item.type == socket.SOCK_STREAM and getattr(item, "status", "") == "LISTEN" and item.laddr:
                    listening_endpoints.add((item.laddr.ip, item.laddr.port))
            except (AttributeError, OSError):
                pass
        for conn in raw:
            proto = "TCP" if conn.type == socket.SOCK_STREAM else "UDP" if conn.type == socket.SOCK_DGRAM else str(conn.type)
            rip, rport = safe_remote(conn)
            lip, lport = safe_local(conn)
            state = getattr(conn, "status", "") or ("LISTEN" if proto == "TCP" and not rip else "—")
            pid = conn.pid if conn.pid is not None else ""
            process = "Unavailable"
            if pid:
                try: process = psutil.Process(pid).name()
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError): pass
            direction = self.classify_direction(proto, state, lip, lport, rip, local_addresses, listening_endpoints)
            record = {"remote_ip":rip, "remote_port":rport, "local_ip":lip, "local_port":lport,
                      "protocol":proto, "state":state, "pid":str(pid), "process":process, "direction":direction}
            records.append(record)
            if rip:
                key = (proto, rip, rport, lip, lport, str(pid))
                observed[key] = record
                previous = self.peers.get(key)
                first = previous["first_seen"] if previous else stamp
                observed[key].update(first_seen=first, last_seen=stamp, first_epoch=previous.get("first_epoch", time.time()) if previous else time.time())
        for key, old in list(self.peers.items()):
            if key not in observed:
                ended = dict(old)
                ended["classification"] = "Previously observed/disconnected peer"
                ended["disconnected_at"] = stamp
                ended["duration"] = self.duration(old.get("first_epoch", time.time()))
                self.peer_history.insert(0, ended)
        self.peer_history = self.peer_history[:300]
        self.peers = observed
        self.events.put(("connections", records, observed))

    @staticmethod
    def classify_direction(proto, state, lip, lport, rip, local_addresses, listening_endpoints):
        if proto == "UDP":
            return "Unknown"
        if state == "LISTEN":
            return "Listening"
        if not rip or state != "ESTABLISHED":
            return "Unknown"
        try:
            local_port = int(lport)
        except (TypeError, ValueError):
            return "Unknown"
        # An accepted TCP socket commonly shares its local endpoint with the
        # listening socket. Otherwise classify a locally-bound established
        # socket as outbound; report Unknown if the local address is unfamiliar.
        if (lip, local_port) in listening_endpoints or ("0.0.0.0", local_port) in listening_endpoints:
            return "Inbound"
        if lip in local_addresses:
            return "Outbound"
        return "Unknown"

    @staticmethod
    def duration(epoch):
        seconds = max(0, int(time.time() - epoch))
        return f"{seconds//3600:02d}:{(seconds%3600)//60:02d}:{seconds%60:02d}"

    def filtered_connections(self):
        query = self.search_var.get().strip().lower()
        result = []
        for row in self.connections:
            ip = row["remote_ip"]
            if self.hide_local_var.get() and ip in ("127.0.0.1", "::1"): continue
            if self.hide_private_var.get() and ip:
                try:
                    if ipaddress.ip_address(ip).is_private: continue
                except ValueError: pass
            if query and query not in " ".join(row.values()).lower(): continue
            result.append(row)
        return result

    def render_connections(self):
        if not hasattr(self, "conn_tree"): return
        self.conn_tree.delete(*self.conn_tree.get_children())
        rows = self.filtered_connections()
        for row in rows:
            self.conn_tree.insert("", "end", values=tuple(row[c] for c in ("remote_ip","remote_port","local_ip","local_port","protocol","state","pid","process","direction")))
        self.conn_count_var.set(f"{len(rows)} displayed / {len(self.connections)} total")

    def render_peers(self):
        self.peer_tree.delete(*self.peer_tree.get_children())
        rows = []
        for row in self.peers.values():
            r = dict(row)
            if r["protocol"] == "UDP": r["classification"] = "UDP endpoint"
            elif r["state"] == "LISTEN": r["classification"] = "Listening TCP socket"
            elif r["state"] == "ESTABLISHED": r["classification"] = "Established TCP peer"
            elif r["direction"] == "Outbound": r["classification"] = "Outbound TCP connection"
            else: r["classification"] = "TCP peer (direction unknown)"
            r["duration"] = self.duration(r.get("first_epoch", time.time()))
            rows.append(r)
        rows.extend(self.peer_history)
        for row in rows:
            self.peer_tree.insert("", "end", values=tuple(row.get(c, "") for c in
                ("classification","remote_ip","remote_port","local_ip","local_port","protocol","state","pid","process","first_seen","last_seen","duration","direction")))
        self.peer_count_var.set(f"{len(self.peers)} currently observed / {len(self.peer_history)} recently disconnected")

    def peer_export_rows(self):
        rows = []
        for row in self.peers.values():
            r = dict(row)
            r["classification"] = "UDP endpoint" if r["protocol"] == "UDP" else ("Established TCP peer" if r["state"] == "ESTABLISHED" else "TCP connection")
            r["duration"] = self.duration(r.get("first_epoch", time.time()))
            rows.append(r)
        return rows + self.peer_history

    def export_rows(self, rows, prefix):
        if not rows:
            messagebox.showinfo("Export", "There are no records to export.")
            return
        initial = self.settings.get("export_directory", str(Path.home()))
        filename = filedialog.asksaveasfilename(initialdir=initial, initialfile=f"kornet_{prefix}_{datetime.now():%Y%m%d_%H%M%S}.csv",
                                                defaultextension=".csv", filetypes=[("CSV files","*.csv")])
        if not filename: return
        keys = list(dict.fromkeys(k for row in rows for k in row.keys() if not k.endswith("_epoch")))
        try:
            with open(filename, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=keys, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
            self.status_var.set(f"Exported {len(rows)} records")
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc))

    def validate_network(self):
        try:
            network = ipaddress.ip_network(self.network_var.get().strip(), strict=False)
            if network.version != 4 or not network.is_private:
                raise ValueError("Enter a private IPv4 CIDR range, such as 192.168.1.0/24.")
            if network.num_addresses > MAX_HOSTS:
                raise ValueError(f"Network contains more than {MAX_HOSTS} addresses.")
            hosts = list(network.hosts())
            if not hosts:
                raise ValueError("The selected network has no usable host addresses.")
            return hosts
        except ValueError as exc:
            messagebox.showerror("Invalid network", str(exc))
            return None

    def scan_custom(self):
        try:
            port = int(self.port_var.get())
            if not 1 <= port <= 65535: raise ValueError
        except ValueError:
            messagebox.showerror("Invalid port", "Enter a TCP port from 1 to 65535.")
            return
        self.start_scan([port], "custom")

    def scan_common(self):
        self.start_scan(COMMON_PORTS, "common")

    def scan_all(self):
        self.start_scan(range(1, 65536), "all")

    def start_scan(self, ports, mode):
        if self.scan_thread and self.scan_thread.is_alive():
            messagebox.showinfo("Scan running", "Stop the current scan before starting another.")
            return
        hosts = self.validate_network()
        if hosts is None: return
        self.stop_event.clear()
        self.scan_rows = []
        self.scan_tree.delete(*self.scan_tree.get_children())
        self.scan_bar["value"] = 0
        self.scan_bar["maximum"] = len(hosts)
        self.scan_progress.set(f"Scanning {len(hosts)} hosts…")
        self.scan_status = "Running"
        self.dash_scan_var.set("LAN scanning: Running")
        self.scan_thread = threading.Thread(target=self.run_scan, args=(hosts, ports, mode), daemon=True)
        self.scan_thread.start()

    def probe(self, ip, port):
        timeout = float(self.settings.get("socket_timeout", 0.35))
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                return sock.connect_ex((str(ip), int(port))) == 0
        except OSError:
            return False

    def run_scan(self, hosts, ports, mode):
        total = len(hosts)
        found = 0
        concurrency = int(self.settings.get("max_concurrency", 64))
        try:
            # Submit bounded batches so a 65,535-port scan does not allocate
            # tens of thousands of pending Future objects at once.
            batch_size = max(concurrency, concurrency * 4)
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                for index, ip in enumerate(hosts, 1):
                    if self.stop_event.is_set(): break
                    open_ports = []
                    port_iter = iter(ports)
                    while not self.stop_event.is_set():
                        batch = []
                        try:
                            for _ in range(batch_size):
                                batch.append(next(port_iter))
                        except StopIteration:
                            pass
                        if not batch:
                            break
                        futures = [pool.submit(self.probe, ip, port) for port in batch]
                        for port, future in zip(batch, futures):
                            if self.stop_event.is_set():
                                break
                            try:
                                if future.result(): open_ports.append(port)
                            except Exception:
                                pass
                        if len(batch) < batch_size:
                            break
                    for port in open_ports:
                        found += 1
                        row = {"ip":str(ip), "port":port, "protocol":"TCP", "status":"Open", "response":"TCP connect succeeded"}
                        self.events.put(("scan_result", row))
                    self.events.put(("scan_progress", index, total, found))
            self.events.put(("scan_done", self.stop_event.is_set(), found))
        except Exception as exc:
            self.events.put(("scan_error", str(exc)))

    def stop_scan(self):
        self.stop_event.set()
        self.scan_progress.set("Stopping scan…")

    def drain_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "connections":
                    self.connections = event[1]
                    self.render_connections()
                    self.render_peers()
                    rows = self.connections
                    self.metric_total.set(str(len(rows)))
                    self.metric_est.set(str(sum(1 for r in rows if r["protocol"] == "TCP" and r["state"] == "ESTABLISHED")))
                    self.metric_listen.set(str(sum(1 for r in rows if r["state"] == "LISTEN")))
                    self.metric_peers.set(str(len(self.peers)))
                    self.local_ip_var.set(local_ipv4())
                    self.status_var.set(f"Last refreshed {datetime.now():%H:%M:%S}")
                elif kind == "error":
                    self.status_var.set(event[1])
                elif kind == "scan_result":
                    row = event[1]
                    self.scan_rows.append(row)
                    self.scan_tree.insert("", "end", values=tuple(row[k] for k in ("ip","port","protocol","status","response")))
                elif kind == "scan_progress":
                    _, done, total, found = event
                    self.scan_bar["value"] = done
                    self.scan_progress.set(f"Checked {done}/{total} hosts — {found} open port(s) found")
                elif kind == "scan_done":
                    _, stopped, found = event
                    self.scan_status = "Stopped" if stopped else "Finished"
                    self.scan_progress.set(f"{self.scan_status} — {found} open port(s) found")
                    self.dash_scan_var.set(f"LAN scanning: {self.scan_status}")
                elif kind == "scan_error":
                    self.scan_progress.set(f"Scan error: {event[1]}")
                    self.dash_scan_var.set("LAN scanning: Error")
        except queue.Empty:
            pass
        if not self.closing:
            self.root.after(150, self.drain_events)

    def on_close(self):
        self.closing = True
        self.stop_event.set()
        self.settings["hide_localhost"] = self.hide_local_var.get() if hasattr(self, "hide_local_var") else False
        self.settings["hide_private"] = self.hide_private_var.get() if hasattr(self, "hide_private_var") else False
        try:
            self.settings_path.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except OSError:
            pass
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = KorNetApp(root)
    root.mainloop()
