import pathlib
import tempfile
import unittest
from vram_atlas.collector import compute_tokens_per_watt, find_ai_workloads


class VramAtlasTests(unittest.TestCase):
    def test_tokens_per_watt(self):
        self.assertEqual(compute_tokens_per_watt(24.0, 12.0), 2.0)
        self.assertEqual(compute_tokens_per_watt(0.0, 15.0), 0.0)
        self.assertEqual(compute_tokens_per_watt(18.0, 0.0), 0.0)

    def test_find_ai_workloads_proc_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            p1 = pathlib.Path(tmp) / "9001"
            (p1 / "fd").mkdir(parents=True)
            (p1 / "comm").write_text("llama-server\n")
            (p1 / "status").write_text("Name:\tllama-server\nVmRSS:\t2048000 kB\n")
            res = find_ai_workloads(tmp)
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]["name"], "llama-server")
            self.assertEqual(res[0]["rss_mb"], 2000.0)


if __name__ == "__main__":
    unittest.main()
