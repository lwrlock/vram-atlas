from __future__ import annotations

import math
import os
import threading
from collections import deque

os.environ.setdefault("GSK_RENDERER", "gl")

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk

from .collector import sample_atlas

ATLAS_CSS = b"""
window, window.background, AdwApplicationWindow {
    background-color: #050811;
    background-image: radial-gradient(circle at 25% 18%, rgba(56, 189, 248, 0.12), transparent 50%),
                      radial-gradient(circle at 86% 85%, rgba(168, 85, 247, 0.12), transparent 46%);
    color: #f0f9ff;
}
headerbar, AdwHeaderBar {
    background: #080d1a;
    border-bottom: 1px solid rgba(56, 189, 248, 0.22);
    color: #f0f9ff;
    min-height: 42px;
}
windowcontrols button {
    min-width: 18px;
    min-height: 18px;
    padding: 2px;
    margin: 0 2px;
    border-radius: 9999px;
}
windowcontrols button image {
    -gtk-icon-size: 12px;
}
.sidebar {
    background: #080e1c;
    border-right: 1px solid rgba(56, 189, 248, 0.20);
    padding: 14px 12px;
}
.nav-btn {
    border-radius: 9px;
    padding: 9px 12px;
    font-size: 12.5px;
    font-weight: 600;
    color: #cbd5e1;
    background: transparent;
    border: 1px solid transparent;
}
.nav-btn:hover {
    background: rgba(56, 189, 248, 0.10);
}
.nav-active {
    background: rgba(56, 189, 248, 0.18);
    border: 1px solid rgba(56, 189, 248, 0.42);
    color: #38bdf8;
    font-weight: 700;
}
.pwr-box {
    background: #0b1326;
    border: 1px solid rgba(168, 85, 247, 0.28);
    border-radius: 10px;
    padding: 12px;
}
.atlas-card {
    background: #0b1222;
    border: 1px solid rgba(56, 189, 248, 0.20);
    border-radius: 11px;
    padding: 14px 16px;
}
.st { font-size: 13.5px; font-weight: 700; color: #f8fafc; }
.ss { font-size: 11.5px; color: #94a3b8; }
.hk { font-size: 10px; font-weight: 700; color: #38bdf8; letter-spacing: 0.7px; }
.hv { font-family: monospace; font-size: 20px; font-weight: 800; color: #f8fafc; }
.mono { font-family: monospace; font-size: 12px; color: #e2e8f0; }
.row { padding: 7px 0; border-bottom: 1px solid rgba(255, 255, 255, 0.06); }
"""


class SiliconBusCanvas(Gtk.DrawingArea):
    """Draws Intel Xe iGPU ring, center UMA shared memory interconnect, and NPU ring."""

    def __init__(self) -> None:
        super().__init__()
        self.set_size_request(-1, 215)
        self.set_hexpand(True)
        self._gpu_pct = 0.0
        self._npu_pct = 0.0
        self._gpu_lbl = "0 / 2350 MHz"
        self._npu_lbl = "0 MB • D3"
        self._uma_used = 0.0
        self._uma_shm = 0.0
        self._uma_tot = 32.0
        self.set_draw_func(self._draw)

    def update_state(self, gpu_pct: float, gpu_lbl: str, npu_pct: float, npu_lbl: str, uma_used: float, uma_shm: float, uma_tot: float) -> None:
        self._gpu_pct = max(0.0, min(100.0, gpu_pct))
        self._npu_pct = max(0.0, min(100.0, npu_pct))
        self._gpu_lbl = gpu_lbl
        self._npu_lbl = npu_lbl
        self._uma_used = uma_used
        self._uma_shm = uma_shm
        self._uma_tot = max(1.0, uma_tot)
        self.queue_draw()

    def _ring(self, cr: cairo.Context, cx: float, cy: float, r: float, pct: float, rgb: tuple[float, float, float], title: str, sub: str) -> None:
        cr.set_line_width(11.0)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_source_rgba(rgb[0], rgb[1], rgb[2], 0.16)
        cr.new_sub_path()
        cr.arc(cx, cy, r, 0, math.tau)
        cr.stroke()

        start = -math.pi / 2.0
        end = start + (max(2.0, pct) / 100.0) * math.tau
        cr.set_source_rgba(rgb[0], rgb[1], rgb[2], 0.96)
        cr.new_sub_path()
        cr.arc(cx, cy, r, start, end)
        cr.stroke()

        cr.set_source_rgba(0.96, 0.98, 1.0, 0.98)
        cr.set_font_size(15.0)
        cr.move_to(cx - 16, cy + 5)
        cr.show_text(f"{pct:.0f}%")

        cr.set_source_rgba(0.85, 0.92, 0.98, 0.95)
        cr.set_font_size(11.5)
        cr.move_to(cx - 52, cy + r + 24)
        cr.show_text(title)
        cr.set_source_rgba(0.60, 0.72, 0.85, 0.90)
        cr.set_font_size(10.5)
        cr.move_to(cx - 52, cy + r + 39)
        cr.show_text(sub)

    def _draw(self, _a, cr: cairo.Context, w: int, h: int) -> None:
        cr.set_source_rgba(0.03, 0.05, 0.10, 0.95)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        r = min(46.0, h * 0.25)
        cy = h * 0.41
        gx, nx = w * 0.20, w * 0.80
        self._ring(cr, gx, cy, r, self._gpu_pct, (0.22, 0.74, 0.97), "Intel Xe iGPU", self._gpu_lbl)
        self._ring(cr, nx, cy, r, self._npu_pct, (0.66, 0.33, 0.97), "Intel NPU (accel0)", self._npu_lbl)

        # Center Unified Memory (UMA) Bus Box
        bx0, bx1 = gx + r + 24.0, nx - r - 24.0
        if bx1 - bx0 > 90.0:
            cr.set_source_rgba(0.22, 0.74, 0.97, 0.30)
            cr.set_line_width(1.6)
            cr.move_to(gx + r + 8, cy)
            cr.line_to(bx0, cy)
            cr.move_to(bx1, cy)
            cr.line_to(nx - r - 8, cy)
            cr.stroke()

            bw = bx1 - bx0
            bh = 82.0
            by = cy - bh * 0.5
            cr.set_source_rgba(0.07, 0.11, 0.20, 0.96)
            cr.rectangle(bx0, by, bw, bh)
            cr.fill()
            cr.set_source_rgba(0.22, 0.74, 0.97, 0.36)
            cr.rectangle(bx0, by, bw, bh)
            cr.stroke()

            cr.set_source_rgba(0.22, 0.74, 0.97, 0.95)
            cr.set_font_size(10.5)
            cr.move_to(bx0 + 12, by + 20)
            cr.show_text(f"UMA SHARED POOL  ({self._uma_tot:.1f} GB)")

            # Segmented bar inside UMA box
            pbx, pby, pbw, pbh = bx0 + 12, by + 34, bw - 24, 14
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.08)
            cr.rectangle(pbx, pby, pbw, pbh)
            cr.fill()
            u_f = min(1.0, self._uma_used / self._uma_tot)
            s_f = min(u_f, self._uma_shm / self._uma_tot)
            cr.set_source_rgba(0.22, 0.74, 0.97, 0.85)
            cr.rectangle(pbx, pby, pbw * u_f, pbh)
            cr.fill()
            cr.set_source_rgba(0.66, 0.33, 0.97, 0.95)
            cr.rectangle(pbx, pby, pbw * s_f, pbh)
            cr.fill()

            cr.set_source_rgba(0.80, 0.88, 0.96, 0.90)
            cr.set_font_size(10.0)
            cr.move_to(bx0 + 12, by + 68)
            cr.show_text(f"Used: {self._uma_used:.2f} GB  •  Shmem/DMA-BUF: {self._uma_shm:.2f} GB")


class ClockHistoryCanvas(Gtk.DrawingArea):
    """Rolling dual-trace clock history for GPU (cyan) & NPU (violet)."""

    def __init__(self) -> None:
        super().__init__()
        self.set_size_request(-1, 145)
        self.set_hexpand(True)
        self._gpu_hist: deque[float] = deque(maxlen=50)
        self._npu_hist: deque[float] = deque(maxlen=50)
        self.set_draw_func(self._draw)

    def push(self, gpu_mhz: float, npu_mhz: float) -> None:
        self._gpu_hist.append(gpu_mhz)
        self._npu_hist.append(npu_mhz)
        self.queue_draw()

    def _draw(self, _a, cr: cairo.Context, w: int, h: int) -> None:
        cr.set_source_rgba(0.03, 0.05, 0.10, 0.95)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        pad_l, pad_r, pad_t, pad_b = 54.0, 12.0, 14.0, 20.0
        cw = max(20.0, w - pad_l - pad_r)
        ch = max(20.0, h - pad_t - pad_b)
        peak = max(1600.0, max(max(self._gpu_hist, default=0.0), max(self._npu_hist, default=0.0)) * 1.1)

        for frac in (0.0, 0.5, 1.0):
            y = pad_t + ch * (1.0 - frac)
            cr.set_source_rgba(0.22, 0.74, 0.97, 0.14)
            cr.move_to(pad_l, y); cr.line_to(w - pad_r, y); cr.stroke()
            cr.set_source_rgba(0.65, 0.75, 0.88, 0.80)
            cr.set_font_size(9.5)
            cr.move_to(4, y + 3)
            cr.show_text(f"{peak * frac:.0f}MHz")

        for series, rgb in ((self._gpu_hist, (0.22, 0.74, 0.97)), (self._npu_hist, (0.66, 0.33, 0.97))):
            if len(series) >= 2:
                cr.set_source_rgba(rgb[0], rgb[1], rgb[2], 0.95)
                cr.set_line_width(2.2)
                n = len(series)
                for i, v in enumerate(series):
                    x = pad_l + (i / (n - 1)) * cw
                    y = pad_t + ch * (1.0 - min(1.0, v / peak))
                    cr.move_to(x, y) if i == 0 else cr.line_to(x, y)
                cr.stroke()


class AtlasWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="VRAM Atlas", default_width=1120, default_height=730)
        self._busy = False
        self._nav_btns: dict[str, Gtk.Button] = {}

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(outer)
        outer.append(Adw.HeaderBar(title_widget=Adw.WindowTitle(title="VRAM Atlas", subtitle="DRM GPU • Intel NPU (accel0) • Unified Memory")))

        shell = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True)
        outer.append(shell)

        # Left Topology Navigation Sidebar (235px)
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        sidebar.add_css_class("sidebar")
        sidebar.set_size_request(235, -1)

        side_hdr = Gtk.Label(label="SILICON TOPOLOGY", xalign=0.0)
        side_hdr.add_css_class("hk")
        sidebar.append(side_hdr)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_UP_DOWN, transition_duration=160, hexpand=True, vexpand=True)
        nav_items = [
            ("matrix", "Compute & UMA Matrix"),
            ("gpu", "GPU Engine (card0)"),
            ("npu", "Intel NPU (accel0)"),
            ("llm", "AI Workloads & Tok/W"),
        ]
        for key, label in nav_items:
            b = Gtk.Button(label=label)
            b.add_css_class("nav-btn")
            b.connect("clicked", self._select_page, key)
            sidebar.append(b)
            self._nav_btns[key] = b
        self._nav_btns["matrix"].add_css_class("nav-active")

        spacer = Gtk.Box(vexpand=True)
        sidebar.append(spacer)

        # Bottom Power & Efficiency Summary Box inside Sidebar
        pwr = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        pwr.add_css_class("pwr-box")
        pk = Gtk.Label(label="POWER & LLM EFF.", xalign=0.0); pk.add_css_class("hk")
        self.sb_watts = Gtk.Label(label="-- W", xalign=0.0); self.sb_watts.add_css_class("hv")
        self.sb_tokw = Gtk.Label(label="llama.cpp standby", xalign=0.0, wrap=True); self.sb_tokw.add_css_class("ss")
        self.sb_uma = Gtk.Label(label="UMA: -- / -- GB", xalign=0.0); self.sb_uma.add_css_class("mono")
        pwr.append(pk); pwr.append(self.sb_watts); pwr.append(self.sb_tokw); pwr.append(self.sb_uma)
        sidebar.append(pwr)
        shell.append(sidebar)

        # Right Stack Content
        content_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True, margin_top=14, margin_bottom=14, margin_start=16, margin_end=16)
        content_wrap.append(self.stack)
        shell.append(content_wrap)

        # Page 1: Compute & UMA Matrix
        p_matrix = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        bus_card = self._card("Dual-Accelerator & UMA Shared Bus", "Live Intel Xe iGPU, Intel NPU (intel_vpu), and /proc/meminfo pool")
        self.bus_canvas = SiliconBusCanvas()
        bus_card.append(self.bus_canvas)
        p_matrix.append(bus_card)

        bottom_grid = Gtk.Grid(column_spacing=12, column_homogeneous=True)
        clk_card = self._card("Rolling Clock Waveform", "Cyan: GPU Cur MHz  •  Violet: NPU MHz")
        self.clk_canvas = ClockHistoryCanvas()
        clk_card.append(self.clk_canvas)

        top_proc_card = self._card("Top DRM / Accel File Holders", "Live scan of /proc/[pid]/fd")
        self.top4_rows = self._make_proc_rows(top_proc_card, 4)

        bottom_grid.attach(clk_card, 0, 0, 1, 1)
        bottom_grid.attach(top_proc_card, 1, 0, 1, 1)
        p_matrix.append(bottom_grid)

        # Page 2: GPU Engine Details
        p_gpu = self._card("DRM Graphics Engine Details (/sys/class/drm/card*)", "Clock frequency bounds, driver, power state & active profile")
        self.gpu_kv = self._make_kv_table(p_gpu, [
            ("node", "DRM Node"),
            ("driver", "Kernel Driver"),
            ("vendor", "PCI Vendor ID"),
            ("cur_mhz", "Current / Requested Clock"),
            ("act_mhz", "Actual SLPC Clock"),
            ("max_mhz", "RP0 Max Clock"),
            ("pstate", "Runtime D-State"),
            ("profile", "DPM / SLPC Profile"),
        ])

        # Page 3: Intel NPU Details
        p_npu = self._card("Intel NPU Accelerator (/sys/class/accel/accel0)", "Hardware microsecond busy duty cycle and allocated memory")
        self.npu_kv = self._make_kv_table(p_npu, [
            ("present", "Device Present"),
            ("name", "Accel Node"),
            ("driver", "Kernel Driver"),
            ("cur_mhz", "Current Clock"),
            ("max_mhz", "Max Frequency"),
            ("util_pct", "Utilization Duty"),
            ("mem_mb", "NPU Memory Allocation"),
            ("pstate", "Runtime D-State"),
        ])

        # Page 4: AI Workloads & Tok/W
        p_llm = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        llm_status = self._card("Local LLM Server & System Energy Efficiency", "Polls http://127.0.0.1:8080/metrics for llama.cpp predicted tokens/sec")
        self.llm_kv = self._make_kv_table(llm_status, [
            ("watts", "Total System Draw"),
            ("tps", "llama.cpp Throughput"),
            ("tpw", "Inference Efficiency (Tokens / Watt)"),
            ("uma_free", "Available UMA Pool Headroom"),
        ])
        llm_procs = self._card("Active Inference & Graphics Processes", "Ranked by Resident Memory (VmRSS) with open render/accel handles")
        self.all6_rows = self._make_proc_rows(llm_procs, 6)
        p_llm.append(llm_status)
        p_llm.append(llm_procs)

        self.stack.add_named(p_matrix, "matrix")
        self.stack.add_named(p_gpu, "gpu")
        self.stack.add_named(p_npu, "npu")
        self.stack.add_named(p_llm, "llm")

        self._bind_keys()
        GLib.timeout_add(140, self._warmup_tick)
        GLib.timeout_add(450, self._warmup_tick)
        GLib.timeout_add(850, self._warmup_tick)
        GLib.timeout_add(1500, self._tick)

    def _bind_keys(self) -> None:
        ctrl = Gtk.EventControllerKey()
        keys = ["matrix", "gpu", "npu", "llm"]

        def _on_key(_c, keyval, _code, state):
            if state & Gdk.ModifierType.ALT_MASK:
                for i, k in enumerate(keys):
                    if keyval == getattr(Gdk, f"KEY_{i + 1}"):
                        self._select_page(None, k)
                        return True
            return False

        ctrl.connect("key-pressed", _on_key)
        self.add_controller(ctrl)

    def _select_page(self, _btn, name: str) -> None:
        self.stack.set_visible_child_name(name)
        for k, b in self._nav_btns.items():
            b.remove_css_class("nav-active")
            if k == name:
                b.add_css_class("nav-active")

    def _card(self, title: str, sub: str) -> Gtk.Box:
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        b.add_css_class("atlas-card")
        t = Gtk.Label(label=title, xalign=0.0); t.add_css_class("st")
        s = Gtk.Label(label=sub, xalign=0.0); s.add_css_class("ss")
        b.append(t); b.append(s)
        return b

    def _make_kv_table(self, parent: Gtk.Box, fields: list[tuple[str, str]]) -> dict[str, Gtk.Label]:
        out: dict[str, Gtk.Label] = {}
        for k, title in fields:
            r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            r.add_css_class("row")
            kl = Gtk.Label(label=title, xalign=0.0, hexpand=True); kl.add_css_class("ss")
            vl = Gtk.Label(label="—", xalign=1.0); vl.add_css_class("mono")
            r.append(kl); r.append(vl)
            parent.append(r)
            out[k] = vl
        return out

    def _make_proc_rows(self, parent: Gtk.Box, count: int) -> list[tuple[Gtk.Label, Gtk.Label]]:
        rows = []
        for i in range(count):
            r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            r.add_css_class("row")
            nl = Gtk.Label(label=f"#{i + 1} Scanning...", xalign=0.0, hexpand=True); nl.add_css_class("mono")
            vl = Gtk.Label(label="—", xalign=1.0); vl.add_css_class("ss")
            r.append(nl); r.append(vl)
            parent.append(r)
            rows.append((nl, vl))
        return rows

    def _warmup_tick(self) -> bool:
        self._refresh()
        return GLib.SOURCE_REMOVE

    def _tick(self) -> bool:
        self._refresh()
        return GLib.SOURCE_CONTINUE

    def _refresh(self) -> None:
        if self._busy:
            return
        self._busy = True

        def _worker():
            try:
                data = sample_atlas(110)
            except Exception:
                data = None

            def _apply():
                self._busy = False
                if not data:
                    return GLib.SOURCE_REMOVE

                gpus = data.get("gpus", [])
                g0 = gpus[0] if gpus else {}
                cur_m = int(g0.get("cur_mhz", 0) or 0)
                act_m = int(g0.get("act_mhz", 0) or 0)
                max_m = int(g0.get("max_mhz", 2350) or 2350)
                gpu_u = float(g0.get("util_pct", 0.0) or 0.0)
                if gpu_u <= 0.0 and cur_m > 0 and max_m > 0:
                    gpu_u = min(100.0, (cur_m / max_m) * 100.0)

                npu = data.get("npu", {})
                npu_m = float(npu.get("mem_mb", 0.0) or 0.0)
                npu_u = float(npu.get("util_pct", 0.0) or 0.0)
                npu_clk = int(npu.get("cur_mhz", 0) or 0)
                npu_max = int(npu.get("max_mhz", 1600) or 1600)

                uma = data.get("uma", {})
                tot_g = float(uma.get("total_gb", 1.0) or 1.0)
                usd_g = float(uma.get("used_gb", 0.0) or 0.0)
                shm_g = float(uma.get("shmem_gb", 0.0) or 0.0)
                avl_g = float(uma.get("avail_gb", 0.0) or 0.0)
                sys_w = float(data.get("system_watts", 0.0) or 0.0)
                tps = data.get("llama_tps")
                tpw = float(data.get("tokens_per_watt", 0.0) or 0.0)

                self.sb_watts.set_label(f"{sys_w:.2f} W")
                self.sb_tokw.set_label(f"{tpw:.2f} Tok/W ({tps:.1f} tok/s)" if tps else "llama.cpp /metrics offline")
                self.sb_uma.set_label(f"UMA: {usd_g:.1f} / {tot_g:.0f} GB")

                self.bus_canvas.update_state(
                    gpu_u,
                    f"{cur_m}/{max_m} MHz ({g0.get('power_state', 'D0')})",
                    npu_u,
                    f"{npu_m:.1f} MB • {npu_clk}/{npu_max} MHz",
                    usd_g,
                    shm_g,
                    tot_g,
                )
                self.clk_canvas.push(cur_m, npu_clk)

                self.gpu_kv["node"].set_label(str(g0.get("name", "—")))
                self.gpu_kv["driver"].set_label(str(g0.get("driver", "—")))
                self.gpu_kv["vendor"].set_label(str(g0.get("vendor", "—")))
                self.gpu_kv["cur_mhz"].set_label(f"{cur_m} MHz")
                self.gpu_kv["act_mhz"].set_label(f"{act_m} MHz")
                self.gpu_kv["max_mhz"].set_label(f"{max_m} MHz")
                self.gpu_kv["pstate"].set_label(str(g0.get("power_state", "—")))
                self.gpu_kv["profile"].set_label(str(g0.get("profile", "—")))

                self.npu_kv["present"].set_label("Yes" if npu.get("present") else "No")
                self.npu_kv["name"].set_label(str(npu.get("name", "—")))
                self.npu_kv["driver"].set_label(str(npu.get("driver", "—")))
                self.npu_kv["cur_mhz"].set_label(f"{npu_clk} MHz")
                self.npu_kv["max_mhz"].set_label(f"{npu_max} MHz")
                self.npu_kv["util_pct"].set_label(f"{npu_u:.1f}%")
                self.npu_kv["mem_mb"].set_label(f"{npu_m:.1f} MB")
                self.npu_kv["pstate"].set_label(str(npu.get("power_state", "—")))

                self.llm_kv["watts"].set_label(f"{sys_w:.2f} W")
                self.llm_kv["tps"].set_label(f"{tps:.2f} tok/s" if tps else "Standby (port 8080 closed)")
                self.llm_kv["tpw"].set_label(f"{tpw:.2f} Tok/W" if tps else "—")
                self.llm_kv["uma_free"].set_label(f"{avl_g:.2f} GB free / {tot_g:.2f} GB total")

                wloads = data.get("ai_workloads", [])
                for row_set in (self.top4_rows, self.all6_rows):
                    for idx, (nl, vl) in enumerate(row_set):
                        if idx < len(wloads):
                            w = wloads[idx]
                            devs = ", ".join(w["devices"]) if w["devices"] else "CPU/UMA"
                            nl.set_label(f"{w['name']} ({w['pid']})")
                            vl.set_label(f"{w['rss_mb']:.0f} MB • {devs}")
                        else:
                            nl.set_label(f"#{idx + 1} Idle")
                            vl.set_label("—")
                return GLib.SOURCE_REMOVE

            GLib.idle_add(_apply)

        threading.Thread(target=_worker, daemon=True).start()


class AtlasApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="com.lwrlock.VramAtlas")

    def do_activate(self):
        p = Gtk.CssProvider()
        p.load_from_data(ATLAS_CSS)
        d = Gdk.Display.get_default()
        if d:
            Gtk.StyleContext.add_provider_for_display(d, p, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        win = self.props.active_window or AtlasWindow(self)
        win.present()


def main() -> int:
    return AtlasApp().run(None)


if __name__ == "__main__":
    raise SystemExit(main())
