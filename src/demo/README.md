# Chatbot demo

Run from the repository root using Python 3.12+:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install --require-hashes -r requirements.lock
.venv/Scripts/python.exe -m src.demo.app
```

Use <http://127.0.0.1:8080>. Do not run app.py directly from this directory:
package imports and deployment paths are rooted at the repository.

See the [main guide](../../README.md) for configuration, privacy, analytics, optional
Laya evaluation, container startup and verification. See the
[review](../../docs/review-2026-10-04.md) for findings and acceptance evidence.

The assistant serves a reviewed directory for all eight locations and links to
their official inventory, scheduling, finance and contact pages.
Open /website-demo to present the installable /static/embed.js widget.
See [website integration](../../docs/website-integration-2026-10-04.md) for installation.
Booking confirmations, CRM delivery and in-chat live stock require configured adapters.
