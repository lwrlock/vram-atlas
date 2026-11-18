# VRAM Atlas

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Engine: C + DRM/Accel Sysfs](https://img.shields.io/badge/Engine-C%20%2B%20Intel%20Xe%2FNPU-0ea5e9.svg)](#architecture)
[![UI: GTK4 Cobalt-Cyan](https://img.shields.io/badge/UI-GTK4%20%2B%20Cairo-38bdf8.svg)](#)

**Unified Linux AI & Graphics Accelerator Profiler for Intel Xe/Arc iGPU, Intel NPU (`intel_vpu accel0`), AMD Radeon, Unified Memory (UMA), and local LLM (`llama.cpp` / `ollama`) Tokens-per-Watt efficiency.**

<p align="center">
  <img src="docs/screenshots/showcase.gif" alt="VRAM Atlas Live Matrix" width="900"/>
</p>

## Key Capabilities

- **Intel NPU (`accel0` / `intel_vpu`) Telemetry:** Reads `npu_busy_time_us`, current/max MHz, D-state (`D0`/`D3hot`), and `npu_memory_utilization` directly from kernel `accel` sysfs.
- **Intel Xe SLPC & Radeon DPM Discovery:** Monitors live GPU `cur_freq`/`act_freq`/`rp0_freq`, power profiles, and VRAM/GTT consumers.
- **UMA Shared Memory & AI Workload Watcher:** Tracks Linux `/proc/meminfo` (`Shmem` DMA-BUF vs free pool) alongside active `/dev/accel/*` & `/dev/dri/render*` inference processes.
- **Local LLM `Tokens / Watt` (`Tok/W`):** Combines `llama.cpp` `/metrics` throughput with live battery/RAPL wattage.

## Build & Run

```bash
make all && make test
./vram-atlas-probe --json
PYTHONPATH=src /usr/bin/python3 -m vram_atlas.gui
```

## License

MIT License — Copyright (c) 2026 Furkan (**lwrlock**). Built with assistance from Google DeepMind Antigravity.
