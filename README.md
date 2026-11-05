# Jack Ingram Motors Chatbot Analytics Solution

![GitHub last commit](https://img.shields.io/github/last-commit/rblake2320/jack-ingram-chatbot-analytics)
![GitHub repo size](https://img.shields.io/github/repo-size/rblake2320/jack-ingram-chatbot-analytics)
![License](https://img.shields.io/badge/license-MIT-blue)

## Overview

An AI assistant and analytics service for Jack Ingram Motors and its six brands (Audi, Mercedes-Benz, Nissan,
Porsche, Volkswagen and Volvo), plus the research and proposal documents behind it.

The application lives in [`src/demo`](src/demo/README.md). It is a Python 3.12 FastAPI service that uses
Claude (`claude-opus-5-5`) with tools, and has a deterministic fallback so it keeps working without an API key or
during an outage.

## What the application does

- **Chat** with tool use: inventory search and comparison, current offers, NHTSA VIN decoding, recalls and crash
  ratings, payment, lease and trade-in estimates, appointment booking, lead capture, service-history lookup
- **Scheduling** for service visits and test drives with business hours, holidays, capacity limits and
  calendar (ICS) files
- **Lead capture and CRM delivery** through a transactional outbox: JSON or ADF 1.0 XML, HMAC-signed,
  retried with backoff
- **Live-agent handoff** with a staff console at `/agent`
- **Analytics dashboard** at `/admin`: conversations, conversion, latency, topics, activity heatmap, tool
  health. No raw customer text is stored in analytics.
- **Tamper evidence**: every business event goes into a hash-chained, HMAC-sealed ledger in the same transaction
  as the data
- **Security**: secrets only from the environment, strict CSP, CSRF guard, rate limits shared across workers,
  admin bearer auth, PII-redacting logs

The bundled inventory, offers and service records are **sample data**, and the dealership's addresses and hours
have not been re-verified. See [TURNOVER.md](TURNOVER.md) for the full status, known limitations and the
credential incident that requires key rotation.

## Quick start (Windows PowerShell)

```powershell
git clone https://github.com/rblake2320/jack-ingram-chatbot-analytics.git
cd jack-ingram-chatbot-analytics\src\demo
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
uvicorn chatbot.main:app --reload --port 8080
```

Then open `http://localhost:8080`. Run the tests with `python -m pytest -q`.

## Repository structure

```text
/
├── src/demo/                 # The application (FastAPI), tests, Dockerfile, DigitalOcean app spec
├── docs/                     # Research, proposal, implementation and business documents
│   ├── proposal/
│   ├── analysis/             # website, brand and requirements analysis
│   ├── implementation/
│   └── business/
├── screenshots/              # Site captures used in the analysis
├── TURNOVER.md               # Current status, limitations, operations, troubleshooting
└── .github/                  # CI (tests on Linux + Windows, secret scan, Docker smoke), templates
```

Design notes for individual features (appointments and handoff, inventory search, lead capture, NHTSA plan)
remain at the repository root as `*_implementation.md` and `*_plan.md`.

## Documentation

### Proposal Documents

- [Final Proposal](docs/proposal/final_proposal.md): Complete solution proposal
- [Analytics Proposal](docs/proposal/analytics_proposal.md): Analytics-specific proposal

### Analysis Documents

#### Website Analysis

- [Main Site Analysis](docs/analysis/website_analysis/main_site.md): Jack Ingram Motors main site analysis
- [User Journeys](docs/analysis/website_analysis/user_journeys.md): User journey mapping
- [Technology Stack](docs/analysis/website_analysis/tech_stack.md): Technical stack assessment

#### Brand Analysis

- [Audi Analysis](docs/analysis/brand_analysis/audi.md): Audi Montgomery site analysis
- [Mercedes-Benz Analysis](docs/analysis/brand_analysis/mercedes_benz.md): Mercedes-Benz site analysis
- [Nissan Analysis](docs/analysis/brand_analysis/nissan.md): Nissan site analysis
- [Porsche Analysis](docs/analysis/brand_analysis/porsche.md): Porsche site analysis
- [Volkswagen Analysis](docs/analysis/brand_analysis/volkswagen.md): Volkswagen site analysis

#### Requirements

- [Analytics Requirements](docs/analysis/requirements/analytics_requirements.md): Detailed analytics requirements
- [Metrics Definition](docs/analysis/requirements/metrics.md): Key customer behavior metrics
- [Pain Points Analysis](docs/analysis/requirements/pain_points.md): Dealership customer experience pain points

### Implementation Documents

- [Compatibility Assessment](docs/implementation/compatibility.md): Chatbot compatibility assessment
- [Optimization Recommendations](docs/implementation/optimization.md): Optimization guidance
- [Implementation Plan](docs/implementation/implementation_plan.md): Detailed implementation roadmap
- [Validation Report](docs/implementation/validation.md): Solution validation

### Business Documents

- [Business Enhancements](docs/business/enhancements.md): Business enhancement documentation
- [Feature Mapping](docs/business/feature_mapping.md): Feature-pain point mapping
- [Dashboard Design](docs/business/dashboard_design.md): Analytics dashboard specifications

## Research benchmarks

The proposal documents cite industry figures for dealership chatbots (for example, higher web-to-lead conversion
and more scheduled appointments). They are **projections from third-party research, not measured results of
this code**. The analytics dashboard records this deployment's own conversion, handoff and satisfaction rates.

## Deployment

DigitalOcean App Platform builds `src/demo/Dockerfile` using `src/demo/app.yaml`. Secrets are set in the App
Platform dashboard, never in the repository. See [TURNOVER.md](TURNOVER.md) for configuration, data durability
and operations.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md), and run `python -m ruff check .` and
`python -m pytest -q` in `src/demo` before opening a pull request.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Contact

Project Owner: [rblake2320](https://github.com/rblake2320)
