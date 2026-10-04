"""Transparent baseline and optional local, advisory Laya intent classification."""

import logging
import math
import os
import re
import threading
from pathlib import Path

INTENTS = {
    "hours": "Opening hours or closing time",
    "contact": "Address, telephone, location or human representative",
    "inventory": "Vehicles, models, price or available stock",
    "service": "Maintenance, repairs or servicing",
    "appointment": "Booking, scheduling or arranging a test drive",
    "other": "Greetings or anything else",
}
QUESTIONS = {
    "intent": {"type": "choice", "instructions": "Classify the customer request.", "criteria": INTENTS}
}
PATTERNS = [
    ("appointment", r"\b(book|booking|schedule|appointment)\b|test drive"),
    ("hours", r"\b(hours|open|opening|close|closing)\b"),
    ("contact", r"\b(contact|phone|telephone|address|location|where|human|representative|person)\b"),
    ("service", r"\b(service|maintenance|repair|oil|tire|brake)\b"),
    ("inventory", r"\b(inventory|vehicle|vehicles|car|cars|price|pricing|stock|suvs?)\b"),
]


def baseline(message):
    lowered = message.lower()
    for intent, pattern in PATTERNS:
        if re.search(pattern, lowered):
            return intent
    return "other"


class LayaRouter:
    """No downloads, GPU use, or probability-based authorization."""

    def __init__(self, model_path=""):
        self.agent = None
        self.status = "disabled"
        self.lock = threading.Lock()
        if not model_path:
            self.status = "unavailable"
            return
        try:
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            os.environ["USE_TF"] = "0"
            import laya
            import torch

            torch.set_num_threads(2)
            if not Path(model_path).is_dir():
                raise ValueError("missing_local_checkpoint")
            self.agent = laya.load(model_path, device="cpu")
            self.status = "ready_advisory"
        except Exception:
            logging.getLogger(__name__).warning(
                "Local Laya unavailable; deterministic routing remains active"
            )
            self.status = "unavailable"

    def classify(self, message):
        if self.agent is None:
            return {"status": self.status}
        if len(message) > 500:
            return {"status": "input_too_long"}
        try:
            if not self.lock.acquire(timeout=1):
                return {"status": "busy"}
            try:
                if len(self.agent.tok.encode(message + str(QUESTIONS))) > 240:
                    return {"status": "input_too_long"}
                result = self.agent.predict({"text": message}, QUESTIONS)
            finally:
                self.lock.release()
            answer = result["answers"]["intent"]
            choice = answer.get("choice")
            probabilities = answer.get("probs", answer.get("probabilities", {}))
            if choice not in INTENTS or not isinstance(probabilities, dict) or not probabilities:
                return {"status": "invalid_output"}
            if (
                set(probabilities) != set(INTENTS)
                or any(
                    type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1
                    for p in probabilities.values()
                )
                or abs(sum(probabilities.values()) - 1) > 0.02
            ):
                return {"status": "invalid_output"}
            return {
                "status": "advisory",
                "intent": choice,
                "probabilities": probabilities,
                "model": "convaiinnovations/laya",
                "calibration": "not_validated_for_dealership",
            }
        except Exception:
            return {"status": "inference_error"}
