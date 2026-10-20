"""Fetch only E1's required GT depths, reusing local official Replica assets.

The ZIP index is fetched once in parallel, cached by ETag, and shared. Workers
read local ZIP headers and compressed bytes directly, avoiding a repeated
3.7 MB index download per worker in the original E0 downloader.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import struct
import time
import urllib.request
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
URL = "https://cvg-data.inf.ethz.ch/nice-slam/data/Replica.zip"


class IndexReader(io.RawIOBase):
    def __init__(self, size, segments):
        self.size, self.segments, self.pos = size, segments, 0

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = offset + (self.pos if whence == 1 else self.size if whence == 2 else 0)
        return self.pos

    def read(self, size=-1):
        end = self.size if size < 0 else min(self.size, self.pos + size)
        for offset, content in self.segments:
            if offset <= self.pos and end <= offset + len(content):
                result = content[self.pos - offset:end - offset]
                self.pos = end
                return result
        raise ValueError(f"Attempt to read outside cached ZIP index: {self.pos}:{end}")


def checked_content(info, compressed):
    if info.compress_type == zipfile.ZIP_DEFLATED:
        content = zlib.decompress(compressed, -15)
    elif info.compress_type == zipfile.ZIP_STORED:
        content = compressed
    else:
        raise ValueError(f"Unsupported ZIP compression: {info.compress_type}")
    if len(content) != info.file_size or zlib.crc32(content) != info.CRC:
        raise ValueError(f"CRC/size mismatch: {info.filename}")
    return content


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=16, choices=range(1, 17))
    args = parser.parse_args()
    spec = json.loads((ROOT / "configs/e1_taxonomy.json").read_text())
    destination = ROOT / spec["evaluation_dataset"]
    destination.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with urllib.request.urlopen(urllib.request.Request(URL, headers={"Range": "bytes=0-0"}), timeout=30) as r:
        assert r.status == 206
        size = int(r.headers["Content-Range"].split("/")[-1])
        etag = r.headers.get("ETag")
        r.read()

    def fetch(start, stop):
        for attempt in range(4):
            try:
                headers = {"Range": f"bytes={start}-{stop}"}
                if etag:
                    headers["If-Match"] = etag
                with urllib.request.urlopen(urllib.request.Request(URL, headers=headers), timeout=30) as r:
                    if r.status != 206 or r.headers["Content-Range"] != f"bytes {start}-{stop}/{size}":
                        raise ValueError("Invalid HTTP range response")
                    content = r.read()
                if len(content) != stop - start + 1:
                    raise ValueError("Incomplete HTTP range")
                return content
            except OSError:
                if attempt == 3:
                    raise
                time.sleep(1 + attempt)

    tail = fetch(size - 128, size - 1)
    zip64 = tail.find(b"PK\x06\x06")
    if zip64 < 0:
        raise ValueError("Expected official ZIP64 layout")
    fields = struct.unpack("<4sQ2H2L4Q", tail[zip64:zip64 + 56])
    central_size, central_offset = fields[-2:]
    cache = destination.parent / "zip_index.bin"
    metadata = destination.parent / "zip_index.json"
    if cache.exists() and metadata.exists() and json.loads(metadata.read_text()) == {"etag": etag, "size": size}:
        central = cache.read_bytes()
        assert len(central) == central_size
        print("Reusing cached official ZIP index", flush=True)
    else:
        intervals = [(p, min(central_offset + central_size - 1, p + 131071))
                     for p in range(central_offset, central_offset + central_size, 131072)]
        print(f"Fetching {central_size:,}-byte ZIP index in {len(intervals)} parallel ranges", flush=True)
        with ThreadPoolExecutor(args.workers) as pool:
            central = b"".join(pool.map(lambda pair: fetch(*pair), intervals))
        cache.write_bytes(central)
        metadata.write_text(json.dumps({"etag": etag, "size": size}) + "\n")
    reader = IndexReader(size, [(central_offset, central), (size - 128, tail)])
    with zipfile.ZipFile(reader) as archive:
        catalogue = archive.infolist()
    required = set(range(1, 360, 2)) | set(range(0, 360, 20)) | {0, 82, 148, 222, 298}
    chosen = []
    for info in catalogue:
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Unsafe ZIP member")
        relative = Path(*path.parts[1:]) if path.parts[0] == "Replica" else Path(*path.parts)
        name = path.name
        match = re.fullmatch(r"(frame|depth)(\d+)\.(jpg|png)", name)
        keep = name == "cam_params.json" or ("office0" in path.parts and name == "traj.txt")
        if "office0" in path.parts and match and int(match[2]) < 360:
            keep = match[1] == "frame" or int(match[2]) in required or (destination / relative).exists()
        if keep:
            chosen.append((info, relative))
    assert sum(p.name.startswith("frame") for _, p in chosen) == 360
    print(f"Verified index; selecting {len(chosen)} assets ({len(required)} required GT views)", flush=True)

    def extract(pair):
        info, relative = pair
        target = destination / relative
        content = target.read_bytes() if target.exists() else b""
        reused = len(content) == info.file_size and zlib.crc32(content) == info.CRC
        if not reused:
            header = fetch(info.header_offset, info.header_offset + 29)
            values = struct.unpack("<4s5H3L2H", header)
            if values[0] != b"PK\x03\x04" or values[3] != info.compress_type or values[2] & 1:
                raise ValueError("Invalid/encrypted local ZIP header")
            offset = info.header_offset + 30 + values[-2] + values[-1]
            content = checked_content(info, fetch(offset, offset + info.compress_size - 1))
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".download")
            temporary.write_bytes(content)
            temporary.replace(target)
        return dict(path=str(target.relative_to(ROOT)), bytes=len(content), sha256=hashlib.sha256(content).hexdigest(),
                    zip_crc=info.CRC, reused_local=reused)

    records = []
    with ThreadPoolExecutor(args.workers) as pool:
        for record in pool.map(extract, chosen):
            records.append(record)
            if len(records) % 20 == 0:
                print(f"{len(records)}/{len(chosen)}, elapsed {time.monotonic()-started:.0f}s", flush=True)
    manifest = dict(url=URL, source_script="https://github.com/cvg/nice-slam/blob/master/scripts/download_replica.sh",
                    scene="office0", frame_start=0, frame_stop_exclusive=360, archive_bytes=size, archive_etag=etag,
                    gt_scope="all taxonomy even views + all odd rendered evaluation views; extra locally available depths retained",
                    required_gt_frame_ids=sorted(required), workers=args.workers, files=records,
                    wall_seconds=time.monotonic() - started)
    (ROOT / "configs/e1_replica_download_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Complete: {len(records)} CRC/SHA-verified assets", flush=True)


if __name__ == "__main__":
    main()
