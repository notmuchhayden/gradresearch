"""Fetch only the three registered interval=1 UAVScenes sequence archives."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.cookiejar import CookieJar
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data/E4e/archives"
MANIFEST = ROOT / "configs/e4e_dataset_manifest.json"
SEQUENCES = {
    "HKairport01": ("1XNUFDYVoIRWNS2_-hV3jIlgk1ciyfxUM", 9_898_021_677),
    "AMtown01": ("1RBU4Aj4F3beFAh8o1Gmjr7dDbTSbLdXf", 15_217_419_198),
    "AMvalley01": ("1RTIVChLYu9GvSBuT_Pzxe703Gm1t_jO5", 12_274_794_304),
}


def open_confirmed_download(file_id):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    request = urllib.request.Request(
        f"https://drive.google.com/uc?export=download&id={file_id}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response = opener.open(request, timeout=60)
    content_type = response.headers.get("Content-Type", "")
    if "text/html" not in content_type:
        return opener, response
    page = response.read(100_000).decode("utf-8", "replace")
    response.close()
    fields = dict(re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', page, re.I))
    action_match = re.search(r'<form[^>]+action="([^"]+)"', page, re.I)
    if not action_match or "confirm" not in fields:
        raise RuntimeError(f"Google Drive did not provide a download confirmation form for {file_id}")
    url = action_match.group(1) + "?" + urllib.parse.urlencode(fields)
    return opener, opener.open(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60)


def download(sequence, info):
    file_id, expected_size = info
    DEST.mkdir(parents=True, exist_ok=True)
    filename = f"interval1_{sequence}.zip"
    target = DEST / filename
    partial = target.with_suffix(target.suffix + ".part")
    if target.exists() and target.stat().st_size == expected_size:
        digest = hashlib.sha256()
        with target.open("rb") as f:
            for block in iter(lambda: f.read(8 << 20), b""):
                digest.update(block)
        return sequence, filename, expected_size, digest.hexdigest(), "reused"
    opener, response = open_confirmed_download(file_id)
    if response.status not in (200, 206):
        raise RuntimeError(f"{sequence}: download returned HTTP {response.status}")
    digest = hashlib.sha256()
    count = 0
    with partial.open("wb") as f:
        for block in iter(lambda: response.read(8 << 20), b""):
            f.write(block)
            digest.update(block)
            count += len(block)
    response.close()
    if count != expected_size:
        raise RuntimeError(f"{sequence}: expected {expected_size} bytes, received {count}")
    partial.replace(target)
    return sequence, filename, count, digest.hexdigest(), "downloaded"


def main():
    started = time.time()
    entries = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(download, name, spec): name for name, spec in SEQUENCES.items()}
        for future in as_completed(futures):
            entry = future.result()
            name, filename, size, sha256, state = entry
            print(f"{name}: {state}, {size} bytes, sha256={sha256}", flush=True)
            entries.append({"sequence": name, "file": f"data/E4e/archives/{filename}",
                            "size_bytes": size, "sha256": sha256, "download_state": state})
    doc = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    doc.update({"dataset": "UAVScenes interval=1 CAM_LIDAR", "archive_source": "official Google Drive folder linked by https://github.com/sijieaaa/UAVScenes",
                "input_window_seconds": [30, 90], "downloaded_archives": sorted(entries, key=lambda x: x["sequence"]),
                "download_elapsed_seconds": round(time.time() - started, 2)})
    MANIFEST.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(f"manifest: {MANIFEST.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
