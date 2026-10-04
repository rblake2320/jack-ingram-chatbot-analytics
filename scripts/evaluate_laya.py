"""Preregistered English routing evaluation of the exact supplied cached checkpoint."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import statistics
import sys
import time
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["USE_TF"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.demo.routing import LayaRouter, baseline  # noqa: E402

CASES = [
    ("What are your sales hours?", "hours"),
    ("Are you open on Sunday?", "hours"),
    ("When does the showroom close?", "hours"),
    ("Opening time tomorrow?", "hours"),
    ("What is your phone number?", "contact"),
    ("Where is the dealership?", "contact"),
    ("Give me your address", "contact"),
    ("I need to speak with a human", "contact"),
    ("Show me your inventory", "inventory"),
    ("What cars are available?", "inventory"),
    ("What is the price of an Audi Q5?", "inventory"),
    ("Do you have any SUVs?", "inventory"),
    ("I need an oil change", "service"),
    ("Can you repair my brakes?", "service"),
    ("What service do you offer?", "service"),
    ("I need maintenance", "service"),
    ("Book a test drive", "appointment"),
    ("Can I schedule a service appointment?", "appointment"),
    ("I want to arrange a test drive", "appointment"),
    ("Help me book an appointment", "appointment"),
    ("Hello", "other"),
    ("Thank you", "other"),
    ("Tell me a joke", "other"),
    ("The weather is lovely", "other"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    import torch
    from huggingface_hub import snapshot_download

    torch.set_num_threads(2)
    snapshot = snapshot_download(
        "convaiinnovations/laya",
        local_files_only=True,
        allow_patterns=["rl_agent_config.json", "model.safetensors", "tokenizer/*", "encoder/*"],
    )
    started = time.perf_counter()
    router = LayaRouter(snapshot)
    if router.agent is None:
        raise RuntimeError("cached_checkpoint_unavailable")
    load_seconds = time.perf_counter() - started
    rows = []
    for text, expected in CASES:
        started = time.perf_counter()
        answer = router.classify(text)
        rows.append(
            {
                "text": text,
                "expected": expected,
                "baseline": baseline(text),
                "laya": answer,
                "milliseconds": round((time.perf_counter() - started) * 1000, 2),
            }
        )
    result = {
        "model": "convaiinnovations/laya",
        "sdk": importlib.metadata.version("laya"),
        "revision": Path(snapshot).name,
        "device": "cpu",
        "threads": 2,
        "input_type": "synthetic short English text, not screenshots or customer transcripts",
        "corpus_sha256": hashlib.sha256(json.dumps(CASES).encode()).hexdigest(),
        "cases": len(rows),
        "baseline_correct": sum(r["baseline"] == r["expected"] for r in rows),
        "laya_correct": sum(r["laya"].get("intent") == r["expected"] for r in rows),
        "valid_results": sum(r["laya"].get("status") == "advisory" for r in rows),
        "load_seconds": round(load_seconds, 2),
        "median_milliseconds": statistics.median(r["milliseconds"] for r in rows),
        "release_policy": "Advisory only; no probability threshold grants action or overrides baseline.",
        "acceptance_target": "At least 22/24 labels, all typed outputs valid; domain calibration still required.",
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, indent=2))
    return 0 if result["valid_results"] == 24 else 1


if __name__ == "__main__":
    raise SystemExit(main())
