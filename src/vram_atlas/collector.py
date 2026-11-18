from __future__ import annotations

import glob
import json
import pathlib
import subprocess
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
AI_PROCESS_NAMES = {
    "llama-server", "llama-cli", "llama-bench", "ollama", "ollama_llama_server",
    "vllm", "whisper", "whisper-cli", "python3", "stable-diffusion",
}


def find_ai_workloads(proc_root: str | pathlib.Path = "/proc") -> list[dict]:
    """Scan procfs for local LLM/ML inference engines holding DRM or NPU accel FDs."""
    root = pathlib.Path(proc_root)
    results = []
    if not root.is_dir():
        return results
    for entry in root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            comm = (entry / "comm").read_text(encoding="utf-8", errors="ignore").strip()
            rss_kb = 0
            for ln in (entry / "status").read_text(errors="ignore").splitlines():
                if ln.startswith("VmRSS:"):
                    rss_kb = int(ln.split()[1])
                    break
            fds_dir = entry / "fd"
            accel_nodes = []
            if fds_dir.is_dir():
                for fd in fds_dir.iterdir():
                    try:
                        tgt = fd.resolve().as_posix()
                    except OSError:
                        continue
                    if "/dev/accel/" in tgt or "/dev/dri/render" in tgt or "/dev/nvidia" in tgt:
                        accel_nodes.append(pathlib.Path(tgt).name)
            is_ai_name = comm.lower() in AI_PROCESS_NAMES
            if accel_nodes or (is_ai_name and rss_kb >= 120_000):
                results.append({
                    "pid": pid,
                    "name": comm,
                    "rss_mb": round(rss_kb / 1024.0, 1),
                    "devices": sorted(set(accel_nodes)),
                })
        except (OSError, ValueError):
            continue
    results.sort(key=lambda x: x["rss_mb"], reverse=True)
    return results[:6]


def compute_tokens_per_watt(tokens_per_sec: float, system_watts: float) -> float:
    if tokens_per_sec <= 0.0 or system_watts <= 0.2:
        return 0.0
    return round(tokens_per_sec / system_watts, 2)


def probe_llama_tps(url: str = "http://127.0.0.1:8080/metrics") -> float | None:
    try:
        with urllib.request.urlopen(url, timeout=0.25) as r:
            body = r.read().decode("utf-8", errors="ignore")
        for line in body.splitlines():
            if line.startswith("llamacpp:predicted_tokens_seconds"):
                return float(line.split()[-1])
    except Exception:
        pass
    return None


def sample_atlas(sample_ms: int = 120) -> dict:
    probe = ROOT / "vram-atlas-probe"
    out = subprocess.check_output([str(probe), "--sample-ms", str(sample_ms), "--json"], text=True, timeout=4.0)
    data = json.loads(out)
    data["ai_workloads"] = find_ai_workloads()
    tps = probe_llama_tps()
    sys_w = float(data.get("system_watts", 0.0) or 0.0)
    data["llama_tps"] = tps
    data["tokens_per_watt"] = compute_tokens_per_watt(tps or 0.0, sys_w)
    return data
