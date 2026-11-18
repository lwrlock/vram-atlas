# vram-atlas

Linux GPU, NPU, and shared memory monitor written in C and Python/GTK4.

![vram-atlas screenshot](docs/screenshots/overview.png)

## What it reads

- **DRM GPUs (`/sys/class/drm/card*`):** Reads driver name (`xe`, `i915`, `amdgpu`), current/actual/max clock frequencies, power profiles, and VRAM/GTT metrics where exposed.
- **Intel NPU (`/sys/class/accel/accel0`):** Reads `intel_vpu` busy time, frequency bounds, D-state, and reported memory usage.
- **Shared Memory & Processes:** Parses `/proc/meminfo` (`MemTotal`, `MemAvailable`, `Shmem`) and scans `/proc/[pid]/fd` for processes holding `/dev/dri/render*`, `/dev/accel/*`, or `/dev/nvidia*` handles.
- **Local LLM Throughput (`collector.py`):** Optionally queries `http://127.0.0.1:8080/metrics` (`llamacpp:predicted_tokens_seconds`) and divides by system battery/RAPL wattage (`Tokens/Watt`).

## Build & Run

```bash
make all
make test
./vram-atlas-probe --sample-ms 80 --json
PYTHONPATH=src /usr/bin/python3 -m vram_atlas.gui
```

## Related

[ff-power-manager](https://github.com/lwrlock/ff-power-manager) · [ebpf-latency-guard](https://github.com/lwrlock/ebpf-latency-guard) · [waylens-privacy](https://github.com/lwrlock/waylens-privacy) · [mempulse](https://github.com/lwrlock/mempulse) · [netpulse-bpf](https://github.com/lwrlock/netpulse-bpf) · [nvme-sentinel](https://github.com/lwrlock/nvme-sentinel)

## License

MIT — see [LICENSE](LICENSE).
