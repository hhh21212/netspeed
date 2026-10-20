#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时网速悬浮窗（TrafficMonitor 风格）
======================================
持续读取系统网卡计数器，实时显示下载/上传速度；
置顶悬浮小窗 + 系统托盘常驻。

依赖：psutil, pystray, Pillow
运行：pythonw netspeed.py   （或双击 run.bat）
"""

import json
import os
import sys
import time
from collections import deque

import tkinter as tk

try:
    import psutil
except ImportError:
    sys.stderr.write("缺少依赖 psutil，请先运行：pip install psutil pystray\n")
    raise SystemExit(1)

# ---- 高分屏清晰显示（可选）----
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

# ---- 托盘相关（可选依赖，缺失则仅悬浮窗）----
try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_OK = True
except Exception:
    TRAY_OK = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

DEFAULTS = {
    "unit": "Mbps",
    "alpha": 0.85,
    "topmost": True,
    "pos_x": None,
    "pos_y": None,
}

# 汇总网速时忽略的接口关键字（回环 / WSL / 虚拟机 / 蓝牙）
IGNORE_KEYWORDS = ("loopback", "wsl", "vmnet", "bluetooth")


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_total_bytes():
    """汇总所有非回环/非虚拟网卡的累计字节数，返回 (recv, sent)。"""
    down = up = 0
    try:
        for name, c in psutil.net_io_counters(pernic=True).items():
            low = name.lower()
            if any(k in low for k in IGNORE_KEYWORDS):
                continue
            down += c.bytes_recv
            up += c.bytes_sent
    except Exception:
        pass
    return down, up


class SpeedMonitor:
    """每秒采样网卡计数，计算下载/上传速率（bps），带 EMA 平滑和历史曲线。"""

    def __init__(self):
        self.last_bytes = None
        self.last_time = None
        self.ema_down = 0.0
        self.ema_up = 0.0
        self.history_down = deque(maxlen=60)
        self.history_up = deque(maxlen=60)

    def tick(self):
        now_bytes = get_total_bytes()
        now = time.time()
        down_bps = up_bps = 0.0
        if self.last_bytes is not None and self.last_time is not None:
            dt = now - self.last_time
            if dt > 0:
                down_bps = max(0.0, (now_bytes[0] - self.last_bytes[0])) * 8.0 / dt
                up_bps = max(0.0, (now_bytes[1] - self.last_bytes[1])) * 8.0 / dt
        self.last_bytes = now_bytes
        self.last_time = now

        a = 0.5  # EMA 系数，越大越灵敏
        self.ema_down = a * down_bps + (1 - a) * self.ema_down
        self.ema_up = a * up_bps + (1 - a) * self.ema_up
        self.history_down.append(self.ema_down)
        self.history_up.append(self.ema_up)
        return self.ema_down, self.ema_up


class NetSpeedApp:
    BG = "#14141f"
    DOWN_COLOR = "#4dd0e1"
    UP_COLOR = "#ffb74d"
    DIM_COLOR = "#6b6b7b"

    def __init__(self):
        self.cfg = load_config()
        self.monitor = SpeedMonitor()
        self.tray = None

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", bool(self.cfg["topmost"]))
        self.root.attributes("-alpha", float(self.cfg["alpha"]))

        self._build_ui()
        self._build_menu()
        self._restore_position()
        self._setup_tray()

        self.tick()

    # ---------- UI ----------
    def _build_ui(self):
        self.root.configure(bg=self.BG)
        container = tk.Frame(self.root, bg=self.BG)
        container.pack(padx=12, pady=10)

        self.down_arrow = tk.Label(container, text="↓", fg=self.DOWN_COLOR, bg=self.BG,
                                   font=("Segoe UI", 13, "bold"))
        self.down_arrow.grid(row=0, column=0, sticky="w")
        self.down_label = tk.Label(container, text=self._fmt(0.0), fg=self.DOWN_COLOR, bg=self.BG,
                                   font=("Consolas", 13, "bold"))
        self.down_label.grid(row=0, column=1, sticky="w", padx=(6, 0))

        self.up_arrow = tk.Label(container, text="↑", fg=self.UP_COLOR, bg=self.BG,
                                 font=("Segoe UI", 13, "bold"))
        self.up_arrow.grid(row=1, column=0, sticky="w")
        self.up_label = tk.Label(container, text=self._fmt(0.0), fg=self.UP_COLOR, bg=self.BG,
                                 font=("Consolas", 13, "bold"))
        self.up_label.grid(row=1, column=1, sticky="w", padx=(6, 0))

        self.canvas = tk.Canvas(container, width=170, height=40, bg=self.BG, highlightthickness=0)
        self.canvas.grid(row=2, column=0, columnspan=2, sticky="we", pady=(6, 0))

        for w in (container, self.down_arrow, self.down_label,
                  self.up_arrow, self.up_label, self.canvas):
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._do_drag)
            w.bind("<Button-3>", self._show_menu)

    def _fmt(self, bps):
        if self.cfg["unit"] == "Mbps":
            return f"{bps / 1e6:6.1f} Mbps"
        return f"{bps / 8e6:6.1f} MB/s"

    def _update_labels(self, down, up):
        self.down_label.config(text=self._fmt(down))
        self.up_label.config(text=self._fmt(up))

    def _draw_sparkline(self):
        c = self.canvas
        c.delete("all")
        w = c.winfo_width() or 1
        h = c.winfo_height() or 1
        # 底部基线
        c.create_line(0, h - 1, w, h - 1, fill=self.DIM_COLOR)
        hist_d = list(self.monitor.history_down)
        hist_u = list(self.monitor.history_up)
        maxv = max((hist_d + hist_u) or [0]) or 1.0
        for hist, color in ((hist_d, self.DOWN_COLOR), (hist_u, self.UP_COLOR)):
            if len(hist) < 2:
                continue
            n = len(hist)
            flat = []
            for i, v in enumerate(hist):
                x = i / (n - 1) * (w - 1)
                y = h - 2 - (v / maxv) * (h - 4)
                flat += [x, y]
            c.create_line(*flat, fill=color, width=1)

    # ---------- 拖动 ----------
    def _start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _do_drag(self, event):
        x = self.root.winfo_x() + event.x - self._drag_x
        y = self.root.winfo_y() + event.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    def _restore_position(self):
        if self.cfg.get("pos_x") is not None and self.cfg.get("pos_y") is not None:
            x, y = int(self.cfg["pos_x"]), int(self.cfg["pos_y"])
        else:
            self.root.update_idletasks()
            w = self.root.winfo_width()
            x = self.root.winfo_screenwidth() - w - 40
            y = 60
        self.root.geometry(f"+{x}+{y}")

    # ---------- 右键菜单 ----------
    def _build_menu(self):
        self.menu = tk.Menu(self.root, tearoff=0)

        self.topmost_var = tk.BooleanVar(value=bool(self.cfg["topmost"]))
        self.menu.add_checkbutton(label="置顶显示", variable=self.topmost_var,
                                  command=self._toggle_topmost)

        self.unit_var = tk.StringVar(value=self.cfg["unit"])
        self.menu.add_separator()
        self.menu.add_radiobutton(label="单位：Mbps", value="Mbps", variable=self.unit_var,
                                  command=self._apply_unit)
        self.menu.add_radiobutton(label="单位：MB/s", value="MB/s", variable=self.unit_var,
                                  command=self._apply_unit)

        self.alpha_var = tk.StringVar(value=str(self.cfg["alpha"]))
        self.menu.add_separator()
        for v in ("0.70", "0.85", "1.00"):
            self.menu.add_radiobutton(label=f"透明度 {int(float(v) * 100)}%", value=v,
                                      variable=self.alpha_var, command=self._apply_alpha)

        self.menu.add_separator()
        self.menu.add_command(label="隐藏窗口", command=self.hide_window)
        self.menu.add_command(label="退出", command=self.quit_app)

    def _show_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _toggle_topmost(self):
        self.cfg["topmost"] = self.topmost_var.get()
        self.root.attributes("-topmost", self.cfg["topmost"])
        self._save_config()

    def _apply_unit(self):
        self.cfg["unit"] = self.unit_var.get()
        self._save_config()
        self._update_labels(self.monitor.ema_down, self.monitor.ema_up)

    def _apply_alpha(self):
        self.cfg["alpha"] = float(self.alpha_var.get())
        self.root.attributes("-alpha", self.cfg["alpha"])
        self._save_config()

    # ---------- 显示/退出 ----------
    def hide_window(self):
        self.root.withdraw()

    def show_window(self):
        self.root.deiconify()

    def toggle_visible(self):
        if self.root.state() == "withdrawn":
            self.root.deiconify()
        else:
            self.root.withdraw()

    def quit_app(self):
        self._save_config()
        if TRAY_OK and self.tray is not None:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.root.destroy()

    def _save_config(self):
        try:
            self.cfg["pos_x"] = self.root.winfo_x()
            self.cfg["pos_y"] = self.root.winfo_y()
        except Exception:
            pass
        save_config(self.cfg)

    # ---------- 托盘 ----------
    def _setup_tray(self):
        if not TRAY_OK:
            return
        try:
            def on_toggle(icon, item):
                self.root.after(0, self.toggle_visible)

            def on_quit(icon, item):
                self.root.after(0, self.quit_app)

            menu = pystray.Menu(
                pystray.MenuItem("显示/隐藏", on_toggle, default=True),
                pystray.MenuItem("退出", on_quit),
            )
            self.tray = pystray.Icon("netspeed", self._make_icon_image(), "网速悬浮窗", menu)
            self.tray.run_detached()
        except Exception:
            self.tray = None

    @staticmethod
    def _make_icon_image():
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([6, 6, 58, 58], radius=16, fill=(24, 24, 38, 255))
        # 下载箭头（向下）
        d.polygon([(20, 12), (44, 12), (32, 28)], fill=(77, 208, 225, 255))
        # 上传箭头（向上）
        d.polygon([(20, 52), (44, 52), (32, 36)], fill=(255, 183, 77, 255))
        return img

    # ---------- 主循环 ----------
    def tick(self):
        down, up = self.monitor.tick()
        self._update_labels(down, up)
        self._draw_sparkline()
        self.root.after(1000, self.tick)


def main():
    NetSpeedApp().root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        with open(os.path.join(BASE_DIR, "error.log"), "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        raise
