"""Capture dated public model-year records, including failed lookup receipts."""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.demo.recalls import lookup  # noqa: E402

root = Path(__file__).resolve().parents[1]
snapshots, receipts = {}, []
for vehicle, year in (("porsche-911", 2026), ("porsche-911", 2025), ("vw-atlas", 2026)):
    result = lookup(vehicle, year)
    receipts.append(result)
    if result["status"] == "live":
        snapshots[f"{vehicle}:{year}"] = {key: result[key] for key in ("source_url", "checked_at", "recalls")}
raw = json.dumps(snapshots, indent=2) + "\n"
(root / "src/demo/data/recall_snapshots.json").write_text(raw, encoding="utf-8")
(root / "docs/evidence/2026-10-04/recall-live.json").write_text(
    json.dumps({"queries": receipts, "snapshot_sha256": hashlib.sha256(raw.encode()).hexdigest()}, indent=2)
    + "\n",
    encoding="utf-8",
)
for result in receipts:
    print(result["vehicle"], result["year"], result["status"], len(result["cards"]))
