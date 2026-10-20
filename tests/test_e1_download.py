"""Check ZIP-index parsing and corruption rejection without network access."""
import io
from pathlib import Path
import struct
import sys
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from download_e1_gt import IndexReader, checked_content


class SparseZipTests(unittest.TestCase):
    def test_index_and_member_crc(self):
        stream = io.BytesIO()
        content = b"replica depth fixture" * 100
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("Replica/office0/results/depth000000.png", content)
        raw = stream.getvalue()
        eocd = struct.unpack("<4s4H2LH", raw[-22:])
        size, offset = eocd[-3:-1]
        with zipfile.ZipFile(IndexReader(len(raw), [(offset, raw[offset:])])) as archive:
            info = archive.infolist()[0]
        header = struct.unpack("<4s5H3L2H", raw[:30])
        self.assertEqual(header[3], info.compress_type)
        start = 30 + header[-2] + header[-1]
        compressed = raw[start:start + info.compress_size]
        self.assertEqual(checked_content(info, compressed), content)
        with self.assertRaises(ValueError):
            info.CRC ^= 1
            checked_content(info, compressed)


if __name__ == "__main__":
    unittest.main()
