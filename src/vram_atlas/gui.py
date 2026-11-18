from __future__ import annotations

import math
import os
import threading

os.environ.setdefault("GSK_RENDERER", "gl")

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk

from .collector import sample_atlas

ATLAS_CSS = b"""
window, window.background, AdwApplicationWindow {
    background-color: #060913;
    background-image: radial-gradient(circle at 20% 15%, rgba(14, 165, 233, 0.16), transparent 50%),
                      radial-gradient(circle at 82% 80%, rgba(139, 92, 246, 0.14), transparent 48%);
    color: #f0f9ff;
}
headerbar, AdwHeaderBar {
    background: rgba(8, 13, 24, 0.92);
    border-bottom: 1px solid rgba(56, 189, 248, 0.24);
    color: #f0f9ff;
}
.atlas-card {
    background: rgba(11, 17, 30, 0.94);
    border: 1px solid rgba(56, 189, 248, 0.22);
    border-radius: 16px;
    padding: 15px 18px;
}
.atlas-hero {
    background: rgba(13, 21, 37, 0.95);
    border: 1px solid rgba(56, 189, 248, 0.28);
    border-radius: 15px;
    padding: 14px 16px;
}
.hk { font-size: 10.5px; font-weight: 700; color: #38bdf8; letter-spacing: 0.7px; }
.hv { font-size: 24px; font-weight: 800; color: #f8fafc; }
.hs { font-size: 11.5px; color: #94a3b8; }
.st { font-size: 14px; font-weight: 700; color: #f8fafc; }
.ss { font-size: 11.5px; color: #94a3b8; }
.row { padding: 6px 0; border-bottom: 1px solid rgba(255, 255, 255, 0.06); }
"""


class DualArcGaugeCanvas(Gtk.DrawingArea):
    """Renders GPU clock/util ring and Intel NPU accel0 utilization arc in Cairo."""

    def __init__(self) -> None:
        super().__init__()
        self.set_size_request(-1, 185)
        self.set_hexpand(True)
        self._gpu_pct = 0.0
        self._npu_pct = 0.0
        self._gpu_lbl = "0 MHz"
        self._npu_lbl = "0 MB"
        self.set_draw_func(self._draw)

    def update_arcs(self, gpu_pct: float, gpu_lbl: str, npu_pct: float, npu_lbl: str) -> None:
        self._gpu_pct = max(0.0, min(100.0, gpu_pct))
        self._npu_pct = max(0.0, min(100.0, npu_pct))
        self._gpu_lbl = gpu_lbl
        self._npu_lbl = npu_lbl
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

        cr.set_source_rgba(0.95, 0.98, 1.0, 0.98)
        cr.set_font_size(14.5)
        cr.move_to(cx - 20, cy + 4)
        cr.show_text(f"{pct:.0f}%")
        cr.set_source_rgba(0.60, 0.72, 0.85, 0.90)
        cr.set_font_size(10.5)
        cr.move_to(cx - 42, cy + r + 22)
        cr.show_text(title)
        cr.move_to(cx - 42, cy + r + 36)
        cr.show_text(sub)

    def _draw(self, _a, cr: cairo.Context, w: int, h: int) -> None:
        cr.set_source_rgba(0.03, 0.05, 0.10, 0.90)
        cr.rectangle(0, 0, w, h)
        cr.fill()
        r = min(48.0, h * 0.28)
        cy = h * 0.43
        self._ring(cr, w * 0.28, cy, r, self._gpu_pct, (0.22, 0.74, 0.97), "Intel Xe iGPU", self._gpu_lbl)
        self._ring(cr, w * 0.72, cy, r, self._npu_pct, (0.65, 0.55, 0.98), "Intel NPU (accel0)", self._npu_lbl)


class AtlasWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="VRAM Atlas", default_width=1080, default_height=740)
        self._busy = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(root)
        self._title = Adw.WindowTitle(title="VRAM Atlas", subtitle="Unified Intel Xe GPU • Intel NPU (intel_vpu) • AI Memory Matrix")
        root.append(Adw.HeaderBar(title_widget=self._title))

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=14, margin_bottom=16, margin_start=18, margin_end=18)
        root.append(body)

        hero = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True)
        c1, self.h_gpu, self.h_gpu_s = self._hero("GPU CLOCK", "-- MHz", "Probing DRM...")
        c2, self.h_npu, self.h_npu_s = self._hero("NPU ACCEL0", "-- MB", "intel_vpu")
        c3, self.h_uma, self.h_uma_s = self._hero("UNIFIED UMA RAM", "-- GB", "Shared Shmem: --")
        c4, self.h_eff, self.h_eff_s = self._hero("SYSTEM / TOK/W", "-- W", "Local LLM Watcher")
        for i, c in enumerate((c1, c2, c3, c4)):
            hero.attach(c, i, 0, 1, 1)
        body.append(hero)

        mid = Gtk.Grid(column_spacing=14, row_spacing=14, column_homogeneous=True)
        left = self._card("Compute Units Matrix", "Simultaneous iGPU SLPC clock & Intel NPU microsecond utilization")
        self.arcs = DualArcGaugeCanvas()
        left.append(self.arcs)
        self.uma_bar = Gtk.ProgressBar(margin_top=6)
        left.append(self.uma_bar)
        self.uma_lbl = Gtk.Label(label="UMA Pool: scanning...", xalign=0.0)
        self.uma_lbl.add_css_class("ss")
        left.append(self.uma_lbl)

        right = self._card("Active AI / Graphics Consumers", "Live /proc scan matching accel0, renderD128 & local LLM runtimes")
        self.proc_rows = []
        for i in range(6):
            r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            r.add_css_class("row")
            nl = Gtk.Label(label=f"#{i + 1} Scanning...", xalign=0.0, hexpand=True)
            vl = Gtk.Label(label="—", xalign=1.0)
            vl.add_css_class("ss")
            r.append(nl); r.append(vl)
            right.append(r)
            self.proc_rows.append((nl, vl))

        mid.attach(left, 0, 0, 1, 1)
        mid.attach(right, 1, 0, 1, 1)
        body.append(mid)

        GLib.timeout_add(1600, self._tick)
        self._refresh()

    def _hero(self, k: str, v: str, s: str):
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        b.add_css_class("atlas-hero")
        kl = Gtk.Label(label=k, xalign=0.0); kl.add_css_class("hk")
        vl = Gtk.Label(label=v, xalign=0.0); vl.add_css_class("hv")
        sl = Gtk.Label(label=s, xalign=0.0, ellipsize=3); sl.add_css_class("hs")
        b.append(kl); b.append(vl); b.append(sl)
        return b, vl, sl

    def _card(self, t: str, s: str) -> Gtk.Box:
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        b.add_css_class("atlas-card")
        tl = Gtk.Label(label=t, xalign=0.0); tl.add_css_class("st")
        sl = Gtk.Label(label=s, xalign=0.0); sl.add_css_class("ss")
        b.append(tl); b.append(sl)
        return b

    def _tick(self) -> bool:
        self._refresh()
        return GLib.SOURCE_CONTINUE

    def _refresh(self) -> None:
        if self._busy:
            return
        self._busy = True

        def _worker():
            try:
                data = sample_atlas(120)
            except Exception:
                data = None

            def _apply():
                self._busy = False
                if not data:
                    return GLib.SOURCE_REMOVE
                gpus = data.get("gpus", [])
                g0 = gpus[0] if gpus else {}
                cur_m = int(g0.get("cur_mhz", 0) or 0)
                max_m = int(g0.get("max_mhz", 2350) or 2350)
                gpu_u = float(g0.get("util_pct", 0.0) or 0.0)
                if gpu_u <= 0.0 and cur_m > 0 and max_m > 0:
                    gpu_u = min(100.0, (cur_m / max_m) * 100.0)

                npu = data.get("npu", {})
                npu_m = float(npu.get("mem_mb", 0.0) or 0.0)
                npu_u = float(npu.get("util_pct", 0.0) or 0.0)
                npu_clk = int(npu.get("cur_mhz", 0) or 0)

                uma = data.get("uma", {})
                tot_g = float(uma.get("total_gb", 1.0) or 1.0)
                usd_g = float(uma.get("used_gb", 0.0) or 0.0)
                shm_g = float(uma.get("shmem_gb", 0.0) or 0.0)
                sys_w = float(data.get("system_watts", 0.0) or 0.0)
                tps = data.get("llama_tps")
                tpw = float(data.get("tokens_per_watt", 0.0) or 0.0)

                self.h_gpu.set_label(f"{cur_m} MHz")
                self.h_gpu_s.set_label(f"{g0.get('driver', 'xe')} • Max {max_m} MHz ({g0.get('power_state', 'D0')})")
                self.h_npu.set_label(f"{npu_m:.1f} MB")
                self.h_npu_s.set_label(f"{npu_clk}/{npu.get('max_mhz', 1600)} MHz • {npu.get('power_state', 'D3')}")
                self.h_uma.set_label(f"{usd_g:.1f} / {tot_g:.0f} GB")
                self.h_uma_s.set_label(f"GPU/Shmem Pool: {shm_g:.2f} GB")
                self.h_eff.set_label(f"{tpw:.1f} Tok/W" if tps else f"{sys_w:.1f} W")
                self.h_eff_s.set_label(f"llama.cpp {tps:.1f} tok/s @ {sys_w:.1f}W" if tps else "Inference server idle (Standby)")

                self.arcs.update_arcs(gpu_u, f"{cur_m}/{max_m} MHz", npu_u, f"{npu_m:.0f} MB ({npu_clk} MHz)")
                self.uma_bar.set_fraction(min(1.0, usd_g / max(1.0, tot_g)))
                self.uma_lbl.set_label(f"UMA Allocation: {usd_g:.1f} GB active • {shm_g:.2f} GB DMA-BUF/Shmem • {uma.get('avail_gb', 0.0):.1f} GB free")

                wloads = data.get("ai_workloads", [])
                for idx, (nl, vl) in enumerate(self.proc_rows):
                    if idx < len(wloads):
                        w = wloads[idx]
                        devs = ", ".join(w["devices"]) if w["devices"] else "CPU/UMA"
                        nl.set_label(f"{w['name']} (PID {w['pid']})")
                        vl.set_label(f"{w['rss_mb']:.0f} MB • {devs}")
                    else:
                        nl.set_label(f"#{idx + 1} Idle Slot"); vl.set_label("—")
                return GLib.SOURCE_REMOVE

            GLib.idle_add(_apply)

        threading.Thread(target=_worker, daemon=True).start()


class AtlasApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="com.lwrlock.VramAtlas")

    def do_activate(self):
        p = Gtk.CssProvider(); p.load_from_data(ATLAS_CSS)
        d = Gdk.Display.get_default()
        if d:
            Gtk.StyleContext.add_provider_for_display(d, p, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        win = self.props.active_window or AtlasWindow(self)
        win.present()


def main() -> int:
    return AtlasApp().run(None)


if __name__ == "__main__":
    raise SystemExit(main())
