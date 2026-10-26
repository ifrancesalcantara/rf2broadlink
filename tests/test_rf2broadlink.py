"""Run with: python3 -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
import rf2broadlink as r  # noqa: E402

# Code generated for a FIMEI floor lamp (EV1527, TE 263 µs) and verified on a real
# lamp through a Broadlink RM4 Pro + Home Assistant.
KNOWN_GOOD = (HERE / "fimei_power_in_ha.txt").read_text().strip()


class Princeton(unittest.TestCase):
    def test_matches_verified_packet(self):
        out = r.from_princeton(0x67AE02, te=263)
        self.assertEqual("b64:" + out, KNOWN_GOOD)

    def test_sub_file_gives_same_packet(self):
        out = r.from_sub((HERE / "fimei_power.sub").read_text())
        self.assertEqual("b64:" + out, KNOWN_GOOD)

    def test_shape(self):
        info = r.decode(r.from_princeton(0x67AE02, te=263, frames=6))
        self.assertEqual(info["band"], 433)
        self.assertEqual(info["repeat"], 0)
        self.assertEqual(info["pulses"], 6 * 50)  # 24 bits × 2 + sync × 2
        self.assertTrue(200 < info["duration_ms"] < 330, info)

    def test_315(self):
        self.assertEqual(r.decode(r.from_princeton(1, band=315))["band"], 315)

    def test_code_too_big(self):
        with self.assertRaises(ValueError):
            r.from_princeton(1 << 24)


class Raw(unittest.TestCase):
    def test_merges_and_aligns(self):
        self.assertEqual(r.raw_pulses([-500, 300, 200, -900, -100, 400]), [500, 1000, 400, 10000])

    def test_raw_sub(self):
        sub = "Frequency: 433920000\nProtocol: RAW\nRAW_Data: 300 -900 900 -300\nRAW_Data: 300 -9000\n"
        self.assertEqual(r.decode(r.from_sub(sub))["pulses"], 6)

    def test_unsupported_frequency(self):
        with self.assertRaises(ValueError):
            r.from_sub("Frequency: 868350000\nProtocol: RAW\nRAW_Data: 300 -300\n")


class Cli(unittest.TestCase):
    def test_cli_ha_prefix(self):
        from io import StringIO
        from contextlib import redirect_stdout
        buf = StringIO()
        with redirect_stdout(buf):
            self.assertEqual(r.main(["67AE02", "--te", "263", "--ha"]), 0)
        self.assertEqual(buf.getvalue().strip(), KNOWN_GOOD)


if __name__ == "__main__":
    unittest.main()
