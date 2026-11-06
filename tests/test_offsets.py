import os
import struct
import tempfile
import unittest

from achl import offsets


def fake_pe(timestamp, size_of_image, machine=0x8664):
    data = bytearray(4096)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", data, 0x84, machine)
    struct.pack_into("<I", data, 0x88, timestamp)
    struct.pack_into("<I", data, 0x80 + 24 + 56, size_of_image)
    return bytes(data)


class OffsetsTest(unittest.TestCase):
    def test_known_header(self):
        b = offsets.BUILDS["1.16.4"]["pe"]
        for size in b["size_of_image"]:
            v, kind = offsets.identify_bytes(fake_pe(b["timestamp"], size), "00")
            self.assertEqual((v, kind), ("1.16.4", "matching header"))
        with self.assertRaises(offsets.UnknownBuild):
            offsets.identify_bytes(fake_pe(b["timestamp"], 0x1000), "00")
        with self.assertRaises(offsets.UnknownBuild):
            offsets.identify_bytes(fake_pe(b["timestamp"], b["size_of_image"][0], 0x14C), "00")

    def test_known_hash_wins(self):
        sha = next(iter(offsets.BUILDS["1.16.4"]["sha256"]))
        v, kind = offsets.identify_bytes(fake_pe(1, 2), sha)
        self.assertEqual((v, kind), ("1.16.4", "steam"))

    def test_unknown_build_refused(self):
        with self.assertRaises(offsets.UnknownBuild):
            offsets.identify_bytes(fake_pe(0x12345678, 0x1000), "00")
        with self.assertRaises(offsets.UnknownBuild):
            offsets.identify_bytes(b"not an exe" * 10, "00")

    def test_identify_file(self):
        b = offsets.BUILDS["1.16.4"]["pe"]
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "acs.exe")
            with open(p, "wb") as fh:
                fh.write(fake_pe(b["timestamp"], b["size_of_image"][0]) + b"\0" * 100)
            self.assertEqual(offsets.for_exe(p).version, "1.16.4")

    def test_lookup_and_dll_env(self):
        o = offsets.Offsets("1.16.4")
        self.assertEqual(o.pyi, 0x1559AF0)
        self.assertEqual(o.sim_cars, 0x208)
        with self.assertRaises(AttributeError):
            o.no_such_thing
        env = dict(kv.split("=") for kv in o.dll_env().split(","))
        self.assertEqual(set(env), set(offsets.DLL_NAMES))
        self.assertEqual(int(env["start_race"], 16), 0x141470)

    def test_every_dll_name_exists(self):
        for version in offsets.BUILDS:
            o = offsets.Offsets(version)
            for name in offsets.DLL_NAMES:
                getattr(o, name)


if __name__ == "__main__":
    unittest.main()
