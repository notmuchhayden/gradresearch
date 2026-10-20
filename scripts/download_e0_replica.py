"""Extract a small Replica pilot from the official ZIP using HTTP ranges."""
import argparse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import time
import threading
import urllib.error
import urllib.request
import zipfile
import zlib

URL = "https://cvg-data.inf.ethz.ch/nice-slam/data/Replica.zip"
ROOT = Path(__file__).resolve().parents[1]


class RemoteZip(io.RawIOBase):
    def __init__(self, url):
        self.url = url
        self.pos = 0
        self.blocks = OrderedDict()
        self.block_size = 512 * 1024
        req = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
        with urllib.request.urlopen(req, timeout=60) as response:
            if response.status != 206:
                raise RuntimeError("Server must support byte ranges; full download was not requested")
            self.size = int(response.headers["Content-Range"].split("/")[-1])
            self.etag = response.headers.get("ETag")
            response.read()

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = offset + (0 if whence == 0 else self.pos if whence == 1 else self.size)
        if self.pos < 0:
            raise ValueError("negative seek")
        return self.pos

    def read(self, size=-1):
        end = self.size if size < 0 else min(self.size, self.pos + size)
        parts = []
        while self.pos < end:
            start = self.pos // self.block_size * self.block_size
            if start not in self.blocks:
                stop = min(self.size, start + self.block_size) - 1
                headers = {"Range": f"bytes={start}-{stop}"}
                if self.etag:
                    headers["If-Match"] = self.etag
                for attempt in range(4):
                    try:
                        with urllib.request.urlopen(urllib.request.Request(self.url, headers=headers), timeout=30) as r:
                            if r.status != 206 or r.headers.get("Content-Range") != f"bytes {start}-{stop}/{self.size}":
                                raise RuntimeError("Invalid range response")
                            data = r.read()
                        break
                    except (OSError, urllib.error.URLError):
                        if attempt == 3:
                            raise
                        print(f"Retry range {start}-{stop}, attempt {attempt + 2}/4", flush=True)
                        time.sleep(min(2 ** attempt, 5))
                if len(data) != stop - start + 1:
                    raise IOError("Incomplete HTTP range")
                self.blocks[start] = data
                if len(self.blocks) > 64:
                    self.blocks.popitem(last=False)
            self.blocks.move_to_end(start)
            count = min(end - self.pos, len(self.blocks[start]) - (self.pos - start))
            parts.append(self.blocks[start][self.pos - start:self.pos - start + count])
            self.pos += count
        return b"".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="office0", choices=["office0", "office1", "office2", "office3", "office4", "room0", "room1", "room2"])
    ap.add_argument("--frames", type=int, default=120)
    ap.add_argument("--destination", type=Path, default=ROOT / "data" / "Replica")
    ap.add_argument("--manifest", type=Path, default=ROOT / "configs" / "e0_replica_download_manifest.json")
    ap.add_argument("--rgb-only", action="store_true", help="Do not download GT depth; appropriate for ancestry-only audits")
    ap.add_argument("--reuse-from", type=Path, help="Reuse CRC-verified files from another Replica directory")
    ap.add_argument("--workers", type=int, default=1, choices=range(1, 9))
    args = ap.parse_args()
    if not 2 <= args.frames <= 2000:
        ap.error("frames must be between 2 and 2000")
    destination = args.destination.resolve()
    manifest = {"url": URL, "source_script": "https://github.com/cvg/nice-slam/blob/master/scripts/download_replica.sh",
                "scene": args.scene, "frame_start": 0, "frame_stop_exclusive": args.frames,
                "rgb_only": args.rgb_only, "files": []}
    remote = RemoteZip(URL)
    manifest.update(archive_bytes=remote.size, archive_etag=remote.etag)
    with zipfile.ZipFile(remote) as archive:
        chosen = []
        for info in archive.infolist():
            name = PurePosixPath(info.filename)
            if name.is_absolute() or ".." in name.parts:
                raise ValueError("Unsafe ZIP path")
            if name.name == "cam_params.json" or (args.scene in name.parts and name.name == "traj.txt"):
                chosen.append(info)
            elif args.scene in name.parts:
                match = re.fullmatch(r"(?:frame|depth)(\d+)\.(?:jpg|png)", name.name)
                if match and int(match[1]) < args.frames:
                    if not (args.rgb_only and name.name.startswith("depth")):
                        chosen.append(info)
        if len([i for i in chosen if PurePosixPath(i.filename).name.startswith("frame")]) != args.frames:
            raise RuntimeError("Requested RGB interval missing from archive")
        print(f"Extracting {len(chosen)} files from {remote.size:,}-byte ZIP", flush=True)
        local_archive = threading.local()
        opened_archives = []
        def extract(info):
            parts = PurePosixPath(info.filename).parts
            relative = Path(*parts[1:]) if parts[0] == "Replica" else Path(*parts)
            output = destination / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            content = output.read_bytes() if output.exists() else b""
            if args.reuse_from and not content:
                reusable = args.reuse_from / relative
                if reusable.exists():
                    content = reusable.read_bytes()
            if len(content) != info.file_size or zlib.crc32(content) != info.CRC:
                if args.workers == 1:
                    content = archive.read(info)
                else:
                    if not hasattr(local_archive, "archive"):
                        reader = RemoteZip(URL)
                        if (reader.etag, reader.size) != (remote.etag, remote.size):
                            raise RuntimeError("Archive changed during parallel extraction")
                        local_archive.archive = zipfile.ZipFile(reader)
                        opened_archives.append(local_archive.archive)
                    content = local_archive.archive.read(info.filename)
            if not output.exists() or output.read_bytes() != content:
                output.write_bytes(content)
            return {"path": str(output.relative_to(ROOT)), "bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(), "zip_crc": info.CRC}
        try:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                for index, record in enumerate(pool.map(extract, sorted(chosen, key=lambda i: i.header_offset))):
                    manifest["files"].append(record)
                    if index % 40 == 0:
                        print(f"{index + 1}/{len(chosen)}: {record['path']}", flush=True)
        finally:
            for opened in opened_archives:
                opened.close()
    path = args.manifest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Wrote {path}", flush=True)


if __name__ == "__main__":
    main()
