# Relevant releases: July 4–October 4, 2026

Reviewed official releases and product documentation on October 4. Dates below
are publication dates; vendor benchmark claims are separate from our measurements.

| Technology | Date and primary source | Relevance and decision |
| --- | --- | --- |
| Claude Sonnet 5.5 | September 28, [Anthropic announcement](https://www.anthropic.com/claude-sonnet-5-5) | Current configurable generation option. Provider reports faster output and lower cost per task than Sonnet 5. The app defaults to its documented model ID when generation is enabled; official location facts and links answer locally. No paid inference was run. |
| Laya 0.3.26 | October 3, [official release](https://github.com/NandhaKishorM/laya/releases/tag/v0.3.26) | Pinned optional runtime, already tested against the exact supplied model. New .NET SDK and TypeScript histogram recalibration could help other client stacks; this Python app needs neither. |
| Laya 0.3.25 / 0.3.23 | October 3 / October 1, [release history](https://github.com/NandhaKishorM/laya/releases) | Recent fixes include oversized batch splitting, GPU-device checks and ONNX quantization defaults; histogram calibration and idle unload are available. Keep CPU advisory mode here. Calibrate with labeled dealership conversations before allowing labels to drive business decisions. |
| Firecrawl monitoring | July 16, [official monitoring guide](https://www.firecrawl.dev/blog/monitor-website-changes-firecrawl) | Can detect changes in published hours/contact information and send a webhook. Useful for future source maintenance; monitor requires an API key and consumes credits. No paid monitor or external webhook was created. The shipped bounded collector supports review candidates and factual change comparison without a paid service. |

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

The original project was missing a working website widget and trustworthy,
store-specific information. These are now implemented: source-backed answers,
exact-origin embedding, iframe style isolation, sessions that survive blocked
third-party cookies, clickable official action links and a presentation page in
the official red/black/white palette. Another vector database or autonomous agent
would add cost without improving this small, structured location directory.
