# Relevant releases: July 4–October 4, 2026

Reviewed official releases and product documentation on October 4. Dates below
are publication dates; vendor benchmark claims are separate from our measurements.

| Technology | Date and primary source | Relevance and decision |
| --- | --- | --- |
| Claude Sonnet 5.5 | September 28, [Anthropic announcement](https://www.anthropic.com/claude-sonnet-5-5) | Current configurable generation option. Provider reports faster output and lower cost per task than Sonnet 5. The app defaults to its documented model ID when generation is enabled; official location facts and links answer locally. No paid inference was run. |
| Laya 0.3.26 | October 3, [official release](https://github.com/NandhaKishorM/laya/releases/tag/v0.3.26) | Pinned optional runtime, already tested against the exact supplied model. New .NET SDK and TypeScript histogram recalibration could help other client stacks; this Python app needs neither. |
| Laya 0.3.25 / 0.3.23 | October 3 / October 1, [release history](https://github.com/NandhaKishorM/laya/releases) | Recent fixes include oversized batch splitting, GPU-device checks and ONNX quantization defaults; histogram calibration and idle unload are available. Keep CPU advisory mode here. Calibrate with labeled dealership conversations before allowing labels to drive business decisions. |
| Firecrawl monitoring | July 16, [official monitoring guide](https://www.firecrawl.dev/blog/monitor-website-changes-firecrawl) | Can detect changes in published hours/contact information and send a webhook. Useful for future source maintenance; monitor requires an API key and consumes credits. No paid monitor or external webhook was created. The shipped bounded collector supports review candidates and factual change comparison without a paid service. |
| SuperSplat 3.5.1 | October 2, [official release](https://github.com/playcanvas/supersplat/releases/tag/v3.5.1) | Recent Gaussian-splat editor update includes an LOD requirement when publishing scenes over 40 million splats. Relevant to photographic tours of actual used-car interiors/exteriors when licensed captures exist. No dealership capture set was supplied or generated; the release is researched, not integrated. |

## Measured Laya suitability

The exact [convaiinnovations/laya](https://huggingface.co/convaiinnovations/laya)
checkpoint receives synthetic short English text, not screenshots. It classifies
typed questions and does not generate the customer-facing chat answer.
The retained 24-case local evaluation returned 24 valid outputs and 22 correct
labels; deterministic routing returned 24 correct labels. Median CPU time was
432.275 ms with two threads on the latest run (the initial run measured 716.935 ms).
SDK 0.3.26 and model revision
7b928d828b7b0e022f929d9bd2e44165aa270148 are recorded in the evidence.

The [model card](https://huggingface.co/convaiinnovations/laya) describes multilingual
and fine-tuned variants, but those were not substituted for the requested checkpoint.
An upstream model-card calibration claim does not establish calibration on dealership
requests. The tested integration remains optional advice and never grants booking,
credit approval, inventory truth or CRM authority.

## Highest-value improvement

The owner identified a larger gap: an answer that sends shoppers away to inventory
does not help them choose. The implemented upgrade now compares reviewed models
inside the chat, follows seating needs across turns, and provides a component
explorer whose chat controls change actual geometry. This is value added to this
demo, without claiming that existing dealership/OEM configurators are absent.

The explorer uses current Three.js 0.186.1, bundled locally with a licensed Carrera
4S exterior, offline Draco decoding, and our original 77-component MY2026 systems
reconstruction. Continuous exploded views, x-ray, source-backed component inspection
and connected official recall details are now implemented. Existing 3D rendering techniques are sufficient
for this interaction; the feature does not depend on a new generative model.
Laya's typed classification cannot create a car model or supply missing stock,
sales ranks or VIN-specific facts. It remains optional advisory routing.

[WebSplatter's author-maintained project](https://websplatter.github.io/) is relevant
research for WebGPU photographic tours, but its [arXiv submission](https://arxiv.org/abs/2602.03207)
is February 3, 2026, outside the requested July 4–October 4 window. The conference
year alone was not used as a recent-release date. Author-reported performance was
not reproduced here, and the project page and preprint report different benchmark
figures. It is a research candidate, not a measured improvement to this app.

For exact used-car condition tours, the necessary next input is a licensed capture
set of the actual vehicle; for in-chat prices/availability it is an authorized
current inventory feed. A generated or generic 3D exterior cannot establish those
facts. The separate licensed exterior states its unknown model year and limited
internals; the new systems reconstruction labels representative geometry and
reviewed public specifications. Its [NHTSA recall integration](https://www.nhtsa.gov/nhtsa-datasets-and-apis)
shows the issue, consequence and manufacturer remedy in the product, with reviewed
camera/lighting links into the model. It preserves model-year and VIN applicability
boundaries. See [actual showroom acceptance](vehicle-explorer-2026-10-04.md).
