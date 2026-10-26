#!/usr/bin/env python3
"""Acquire N2's supplied meshes with official ZIP CRC and immutable hashes."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import zipfile
import zlib

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from download_e3b_replica import SharedRemoteZip


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registration",default="results/N2_dataset_preparation/2026-10-26/registration.json")
    args=parser.parse_args()
    registration=ROOT/args.registration
    spec=json.loads(registration.read_text())
    manifest=registration.parent/"mesh_download_manifest.json"
    if manifest.exists():
        old=json.loads(manifest.read_text())
        assert old["archive_bytes"]==spec["expected_archive_bytes"] and old["archive_etag"]==spec["expected_archive_etag"]
        assert {row["scene"] for row in old["files"]}=={row["scene"] for row in spec["scenes"]}
        for row in old["files"]:
            p=ROOT/row["path"];data=p.read_bytes()
            assert len(data)==row["bytes"] and hashlib.sha256(data).hexdigest()==row["sha256"]
            assert zlib.crc32(data)==row["zip_crc"]
        print("Existing mesh manifest and files verified; unchanged.")
        return
    reader=SharedRemoteZip(spec["source_url"])
    assert reader.size==spec["expected_archive_bytes"] and reader.etag==spec["expected_archive_etag"]
    rows=[]
    with zipfile.ZipFile(reader) as archive:
        for row in spec["scenes"]:
            scene=row["scene"]
            info=archive.getinfo(f"Replica/{scene}_mesh.ply")
            path=ROOT/spec["dataset_root"]/f"{scene}_mesh.ply"
            data=path.read_bytes() if path.exists() else archive.read(info)
            assert len(data)==info.file_size and zlib.crc32(data)==info.CRC
            if not path.exists():
                path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
            rows.append({"scene":scene,"path":str(path.relative_to(ROOT)),"bytes":len(data),
                         "sha256":hashlib.sha256(data).hexdigest(),"zip_crc":info.CRC})
            print(f"{scene}: {len(data)} bytes",flush=True)
    manifest.write_text(json.dumps({"url":spec["source_url"],"archive_bytes":reader.size,
                                   "archive_etag":reader.etag,"files":rows},indent=2)+"\n")


if __name__=="__main__":main()
