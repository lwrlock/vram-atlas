/*
 * accel_probe.c - Unified Intel Xe/Arc iGPU, Intel NPU (intel_vpu), AMD & UMA Probe
 * Reads DRM/accel sysfs and procfs AI workloads with sub-millisecond overhead.
 */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <ctype.h>
#include <dirent.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static bool read_str(const char *path, char *out, size_t sz) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) return false;
    ssize_t n = read(fd, out, sz - 1);
    close(fd);
    if (n <= 0) return false;
    out[n] = '\0';
    while (n > 0 && (out[n - 1] == '\n' || out[n - 1] == '\r' || out[n - 1] == ' ')) {
        out[--n] = '\0';
    }
    return true;
}

static int64_t read_i64(const char *path, int64_t def) {
    char buf[64];
    if (!read_str(path, buf, sizeof(buf))) return def;
    char *end = NULL;
    long long v = strtoll(buf, &end, 10);
    return (end != buf) ? (int64_t)v : def;
}

static void json_esc(const char *s, char *out, size_t sz) {
    size_t j = 0;
    for (size_t i = 0; s && s[i] && j + 2 < sz; i++) {
        unsigned char c = (unsigned char)s[i];
        if (c == '"' || c == '\\') {
            if (j + 2 >= sz) break;
            out[j++] = '\\'; out[j++] = (char)c;
        } else if (c >= 0x20) {
            out[j++] = (char)c;
        }
    }
    out[j] = '\0';
}

typedef struct {
    char name[32];
    char driver[32];
    char vendor[16];
    int64_t cur_mhz;
    int64_t act_mhz;
    int64_t max_mhz;
    double util_pct;
    double vram_used_mb;
    double vram_total_mb;
    char pstate[16];
    char profile[48];
} GpuDev;

typedef struct {
    bool present;
    char name[32];
    char driver[32];
    int64_t cur_mhz;
    int64_t max_mhz;
    double util_pct;
    double mem_mb;
    char pstate[16];
} NpuDev;

static double read_system_watts(void) {
    const char *bats[] = {"/sys/class/power_supply/BAT1", "/sys/class/power_supply/BAT0"};
    for (size_t i = 0; i < 2; i++) {
        char p[128];
        snprintf(p, sizeof(p), "%s/power_now", bats[i]);
        int64_t uw = read_i64(p, -1);
        if (uw > 0) return (double)uw / 1e6;
        snprintf(p, sizeof(p), "%s/current_now", bats[i]);
        int64_t ua = read_i64(p, -1);
        snprintf(p, sizeof(p), "%s/voltage_now", bats[i]);
        int64_t uv = read_i64(p, -1);
        if (ua > 0 && uv > 0) return ((double)ua / 1e6) * ((double)uv / 1e6);
    }
    FILE *hf = fopen("/run/ff-power-manager/telemetry_history.json", "r");
    if (hf) {
        fseek(hf, 0, SEEK_END);
        long sz = ftell(hf);
        if (sz > 4095) fseek(hf, sz - 4095, SEEK_SET);
        else rewind(hf);
        char buf[4096];
        size_t n = fread(buf, 1, sizeof(buf) - 1, hf);
        fclose(hf);
        buf[n] = '\0';
        char *cur = buf, *last = NULL;
        while ((cur = strstr(cur, "\"watts\":")) != NULL) { last = cur; cur += 8; }
        double w = 0.0;
        if (last && sscanf(last, "\"watts\":%lf", &w) == 1 && w > 0.0) return w;
    }
    return 0.0;
}

int main(int argc, char *argv[]) {
    bool as_json = false;
    int sample_ms = 120;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--json") == 0 || strcmp(argv[i], "-j") == 0) as_json = true;
        else if (strcmp(argv[i], "--sample-ms") == 0 && i + 1 < argc) {
            sample_ms = atoi(argv[++i]);
            if (sample_ms < 40) sample_ms = 40;
            if (sample_ms > 1500) sample_ms = 1500;
        }
    }

    /* Sample NPU busy time across window */
    NpuDev npu;
    memset(&npu, 0, sizeof(npu));
    int64_t npu_busy0 = read_i64("/sys/class/accel/accel0/device/npu_busy_time_us", -1);
    usleep((useconds_t)sample_ms * 1000U);
    int64_t npu_busy1 = read_i64("/sys/class/accel/accel0/device/npu_busy_time_us", -1);

    if (access("/sys/class/accel/accel0/device", F_OK) == 0) {
        npu.present = true;
        snprintf(npu.name, sizeof(npu.name), "accel0");
        char dl[256], db[256];
        ssize_t rl = readlink("/sys/class/accel/accel0/device/driver", db, sizeof(db) - 1);
        const char *drv = "intel_vpu";
        if (rl > 0) { db[rl] = '\0'; const char *sl = strrchr(db, '/'); drv = sl ? sl + 1 : db; }
        (void)dl;
        snprintf(npu.driver, sizeof(npu.driver), "%.31s", drv);
        npu.cur_mhz = read_i64("/sys/class/accel/accel0/device/npu_current_frequency_mhz", 0);
        npu.max_mhz = read_i64("/sys/class/accel/accel0/device/npu_max_frequency_mhz", 0);
        int64_t mem_b = read_i64("/sys/class/accel/accel0/device/npu_memory_utilization", 0);
        npu.mem_mb = (double)mem_b / (1024.0 * 1024.0);
        read_str("/sys/class/accel/accel0/device/power_state", npu.pstate, sizeof(npu.pstate));
        if (npu_busy0 >= 0 && npu_busy1 >= npu_busy0) {
            double pct = ((double)(npu_busy1 - npu_busy0) / ((double)sample_ms * 1000.0)) * 100.0;
            if (pct > 100.0) pct = 100.0;
            npu.util_pct = pct;
        }
    }

    GpuDev gpus[4];
    size_t ngpu = 0;
    DIR *drm = opendir("/sys/class/drm");
    if (drm) {
        struct dirent *de;
        while ((de = readdir(drm)) != NULL && ngpu < 4) {
            if (strncmp(de->d_name, "card", 4) != 0 || strchr(de->d_name, '-')) continue;
            char base[320], vp[384];
            snprintf(base, sizeof(base), "/sys/class/drm/%.31s/device", de->d_name);
            snprintf(vp, sizeof(vp), "%s/vendor", base);
            if (access(vp, R_OK) != 0) continue;

            GpuDev *g = &gpus[ngpu];
            memset(g, 0, sizeof(*g));
            snprintf(g->name, sizeof(g->name), "%.31s", de->d_name);
            read_str(vp, g->vendor, sizeof(g->vendor));
            char dl[384], db[256];
            snprintf(dl, sizeof(dl), "%s/driver", base);
            ssize_t rl = readlink(dl, db, sizeof(db) - 1);
            if (rl > 0) { db[rl] = '\0'; const char *sl = strrchr(db, '/'); snprintf(g->driver, sizeof(g->driver), "%.31s", sl ? sl + 1 : db); }
            else strcpy(g->driver, "drm");

            char p1[384], p2[384], p3[384], p4[384], p5[384];
            snprintf(p1, sizeof(p1), "%s/tile0/gt0/freq0/cur_freq", base);
            snprintf(p2, sizeof(p2), "%s/tile0/gt0/freq0/act_freq", base);
            snprintf(p3, sizeof(p3), "%s/tile0/gt0/freq0/rp0_freq", base);
            snprintf(p4, sizeof(p4), "%s/tile0/gt0/freq0/power_profile", base);
            snprintf(p5, sizeof(p5), "%s/power_state", base);
            g->cur_mhz = read_i64(p1, 0);
            g->act_mhz = read_i64(p2, 0);
            g->max_mhz = read_i64(p3, 0);
            if (g->cur_mhz <= 0) {
                snprintf(p1, sizeof(p1), "/sys/class/drm/%s/gt_cur_freq_mhz", de->d_name);
                snprintf(p2, sizeof(p2), "/sys/class/drm/%s/gt_act_freq_mhz", de->d_name);
                snprintf(p3, sizeof(p3), "/sys/class/drm/%s/gt_max_freq_mhz", de->d_name);
                g->cur_mhz = read_i64(p1, 0);
                g->act_mhz = read_i64(p2, 0);
                g->max_mhz = read_i64(p3, 0);
            }
            read_str(p4, g->profile, sizeof(g->profile));
            read_str(p5, g->pstate, sizeof(g->pstate));

            snprintf(p1, sizeof(p1), "%s/gpu_busy_percent", base);
            int64_t busy = read_i64(p1, -1);
            if (busy >= 0) {
                g->util_pct = (double)busy;
            } else if (g->max_mhz > 0 && g->act_mhz > 0) {
                g->util_pct = ((double)g->act_mhz / (double)g->max_mhz) * 100.0;
            }
            snprintf(p1, sizeof(p1), "%s/mem_info_vram_used", base);
            snprintf(p2, sizeof(p2), "%s/mem_info_vram_total", base);
            int64_t vu = read_i64(p1, 0), vt = read_i64(p2, 0);
            g->vram_used_mb = (double)vu / (1024.0 * 1024.0);
            g->vram_total_mb = (double)vt / (1024.0 * 1024.0);
            ngpu++;
        }
        closedir(drm);
    }

    /* Read /proc/meminfo for UMA shared memory pool */
    double mem_total_gb = 0.0, mem_avail_gb = 0.0, shmem_gb = 0.0;
    FILE *mf = fopen("/proc/meminfo", "r");
    if (mf) {
        char line[256];
        unsigned long long kb = 0;
        while (fgets(line, sizeof(line), mf)) {
            if (sscanf(line, "MemTotal: %llu kB", &kb) == 1) mem_total_gb = (double)kb / (1024.0 * 1024.0);
            else if (sscanf(line, "MemAvailable: %llu kB", &kb) == 1) mem_avail_gb = (double)kb / (1024.0 * 1024.0);
            else if (sscanf(line, "Shmem: %llu kB", &kb) == 1) shmem_gb = (double)kb / (1024.0 * 1024.0);
        }
        fclose(mf);
    }

    double sys_w = read_system_watts();

    if (as_json) {
        char npu_drv_e[64], npu_ps_e[32];
        json_esc(npu.driver, npu_drv_e, sizeof(npu_drv_e));
        json_esc(npu.pstate, npu_ps_e, sizeof(npu_ps_e));
        printf("{\n"
               "  \"system_watts\": %.2f,\n"
               "  \"uma\": {\"total_gb\": %.2f, \"used_gb\": %.2f, \"avail_gb\": %.2f, \"shmem_gb\": %.2f},\n"
               "  \"npu\": {\"present\": %s, \"name\": \"%s\", \"driver\": \"%s\", \"cur_mhz\": %ld, \"max_mhz\": %ld, \"util_pct\": %.1f, \"mem_mb\": %.1f, \"power_state\": \"%s\"},\n"
               "  \"gpus\": [",
               sys_w, mem_total_gb, (mem_total_gb - mem_avail_gb), mem_avail_gb, shmem_gb,
               npu.present ? "true" : "false", npu.name, npu_drv_e, (long)npu.cur_mhz, (long)npu.max_mhz, npu.util_pct, npu.mem_mb, npu_ps_e);
        for (size_t i = 0; i < ngpu; i++) {
            char de[64], pe[64], pse[32];
            json_esc(gpus[i].driver, de, sizeof(de));
            json_esc(gpus[i].profile, pe, sizeof(pe));
            json_esc(gpus[i].pstate, pse, sizeof(pse));
            printf("%s\n    {\"name\": \"%s\", \"driver\": \"%s\", \"vendor\": \"%s\", \"cur_mhz\": %ld, \"act_mhz\": %ld, \"max_mhz\": %ld, \"util_pct\": %.1f, \"vram_used_mb\": %.1f, \"vram_total_mb\": %.1f, \"power_state\": \"%s\", \"profile\": \"%s\"}",
                   i == 0 ? "" : ",", gpus[i].name, de, gpus[i].vendor,
                   (long)gpus[i].cur_mhz, (long)gpus[i].act_mhz, (long)gpus[i].max_mhz,
                   gpus[i].util_pct, gpus[i].vram_used_mb, gpus[i].vram_total_mb, pse, pe);
        }
        printf("\n  ]\n}\n");
    } else {
        printf("=== VRAM Atlas Hardware Matrix ===\n");
        printf("  System Draw : %.2f W | UMA RAM: %.1f/%.1f GB used (Shmem: %.2f GB)\n",
               sys_w, mem_total_gb - mem_avail_gb, mem_total_gb, shmem_gb);
        for (size_t i = 0; i < ngpu; i++) {
            printf("  GPU (%s/%s): cur=%ld act=%ld max=%ld MHz | util=%.1f%% | pstate=%s\n",
                   gpus[i].name, gpus[i].driver, (long)gpus[i].cur_mhz, (long)gpus[i].act_mhz,
                   (long)gpus[i].max_mhz, gpus[i].util_pct, gpus[i].pstate);
        }
        if (npu.present) {
            printf("  NPU (%s/%s): cur=%ld max=%ld MHz | util=%.1f%% | mem=%.1f MB | %s\n",
                   npu.name, npu.driver, (long)npu.cur_mhz, (long)npu.max_mhz,
                   npu.util_pct, npu.mem_mb, npu.pstate);
        }
    }
    return 0;
}
