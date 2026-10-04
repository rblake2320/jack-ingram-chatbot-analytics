# Vehicle explorer and useful in-chat advice — October 4, 2026

## Geometry audit after the owner's internal-model screenshot

The earlier first-frame repair did not inspect what appeared after entering the
systems view. The owner's second screenshot was accurate: the red car was the
procedurally generated schematic, and calling it comparable to Eagle Atlas's
source-part exploration overstated its fidelity. This section supersedes any
earlier use of “parts” that could imply Porsche-sourced service geometry.

The local Eagle Atlas asset contains **677 imported mesh instances with 677
source object identities**. The Porsche exterior has **44 displayed imported
surfaces** (45 mesh definitions including a hidden backdrop), **no per-object
component identity**, and **no engine internals**. The separately generated
systems GLB has **165 meshes mapped to 77 named schematic regions**, all geometry
grade D. Its boxes, cylinders and body slabs are authored by our generator; a
larger mesh count does not make them Porsche parts. The exterior reference was
uploaded in 2013 and its actual model year is unverified. No validated MY2026
Carrera 4S source model with OEM internal part hierarchy is in this repository.
The [compact GLB comparison](evidence/2026-10-04/porsche-asset-comparison.json)
retains hashes, mesh-instance counts and identity counts for all three assets.

The showroom now leads to `/vehicle-atlas`, where **Take apart 44 surfaces**
separates the imported meshes individually. Clicking one isolates that actual
source surface; reset restores the car. The layout uses real world-space mesh
bounds, preserves each mesh scale, fits the visible canvas and checks every pair
for projected overlap. The systems tab is labeled an **illustrative system map**;
its transparent licensed shell remains in the cutaway and a badge says its
internals are schematic, not Porsche CAD. The chat's Porsche model card and the
website-demo primary action also open the imported exterior first. This improves
the demonstrable geometry experience without presenting the 77 schematic zones
as an F-15-equivalent digital twin.

Compare the [owner's schematic screenshot](evidence/2026-10-04/porsche-concept-before-owner.png)
with the [now-labeled concept view](evidence/2026-10-04/porsche-concept-labeled-after.png).
Retained [source-surface layout](evidence/2026-10-04/porsche-source-surfaces-desktop.png)
and [individual mesh inspection](evidence/2026-10-04/porsche-source-surface-isolated.png)
show the actual browser result. The [geometry audit receipt](evidence/2026-10-04/porsche-geometry-audit.json)
records desktop, mobile, selection, reset and labeled concept checks.
The refreshed user-facing `:8090` preview passed the
[same shipped HTTP acceptance](evidence/2026-10-04/porsche-live-preview-after.json)
after its template cache was restarted.

## Recognizable exterior and internal exploration

**Failed, repaired, retested:** the first MY2026 systems page opened on its
original box-shaped representative shell. The owner's screenshot showed the
result was not a persuasive Porsche showroom demo. The combined page now opens
on the separately licensed, recognizable Carrera 4S exterior. Its source file
remains unchanged, 44 vehicle surfaces are displayed, and its model year is
explicitly unknown. A click on the car or the X-ray button reveals the original
MY2026 illustrative internal scene. The licensed exterior becomes a faint
silhouette; its wheels and underbody are suppressed in cutaway so they do not
duplicate the internal wheel and brake assemblies. Explode, part selection,
isolation, tour and recall links use the 77-component systems scene. Reset
returns to the recognizable exterior.

Both GLBs are verified by size and SHA-256 before parsing. The runtime measured
their world-space bounding boxes and aligned the licensed visual shell to the
systems envelope with zero reported center/size registration error. This is
visual registration, not proof that the reference is a 2026 configuration or
that the two assets' parts physically fit. The source-model wheels, body shape
and model year remain separate from the public-fact internal reconstruction.
The notice and footer name the artist and CC BY-SA 4.0 rights for the exterior.

**Worked:** a real browser loaded 44 licensed exterior surfaces on the combined
page, switched to X-ray with 165 system meshes, reached 50% spatial explosion,
and reset to the exterior. Clicking the displayed car itself opened cutaway.
The official 2025 camera recall deep link still selected the representative
rear camera region and showed the issue, consequence and remedy. Compare the
[owner's box-shaped first view](evidence/2026-10-04/porsche-boxy-before-owner.png),
the [corrected exterior](evidence/2026-10-04/porsche-corrected-exterior.png),
and the [licensed-shell cutaway](evidence/2026-10-04/porsche-corrected-cutaway.png).
The [browser and Linux receipt](evidence/2026-10-04/porsche-visual-acceptance.json)
retains the exact UI transitions. The packaged Linux build also rendered the
[corrected exterior](evidence/2026-10-04/porsche-visual-linux.png) as uid 1000, exercised X-ray and 50% explosion, and
passed its [HTTP acceptance](evidence/2026-10-04/vehicle-visual-container-http.json).

## Current systems and recall addition

The MY2026 992.2 reconstruction is a separate original asset at
`/vehicle-atlas?subject=systems`: **77 components, 165 meshes, 45,644 triangles,
1,525,460 bytes**. Its source hash is
`5cabbc7f6d75563d14f16ae4ea43c9199f73019c805e2a9d9fa39af46031153a`.
The older licensed exterior remains separately attributed and has no asserted
model year. The reconstruction does not inherit the exterior model's geometry.

The systems scene includes opposed-cylinder/piston references, twin turbo regions,
PDK case and clutch pair, rear and front differentials, propeller shaft, four
half-shafts, staggered wheels/tires, rotors/calipers, PASM damper/spring regions,
cooling/exhaust regions, two front seats, dashboard, steering, body closures,
lighting control and camera regions. Every component has owned GLB mesh indices,
source IDs, identity/geometry/placement grades and null OEM part number. All shapes
are grade D representative geometry. This is a public-fact explanatory scene.

Controls inspired by the F-15 explorer include spatial 0–100% explosion, x-ray, system colors,
wireframe, 3D/top/side/front/rear cameras, turntable, selected-part focus/isolation,
connection traces, source surfaces, collision-filtered labels and a six-stage tour.
The parts inventory is a separate packed view that preserves actual part scale.
The assistant applies bounded, validated actions on both assets.

**Worked:** actual exported vertex buffers and node world transforms measured
4.542 m length, 1.303 m height, width within 3 mm of the 1.852 m specification,
2.450 m axle spacing, 245/35 ZR20 and 305/30 ZR21 tire envelopes, and 408/380 mm
rotors. The initial bumper air opening extended the length to 4.571 m; the geometry
was repaired and retested. See `systems-dimensions-before.txt` and
`porsche-systems-geometry.json`. Browser reassembly measured zero component-center
drift. All 77 illustrative regions packed with zero overlaps and fit the desktop and mobile canvas.
The final phone-width test measured 390 × 844 CSS pixels, scroll width 378,
all 165 meshes present and zero packed overlaps. A 50% explosion, top view and
wireframe were exercised through native controls. The full tour completed and
restored all geometry. Browser overrides were reset after testing.

**Worked:** the embedded chat's `2025 Porsche 911 recalls` reply displays official
issue, consequence and remedy. Its actual camera-notice link opens our local
viewer, displays NHTSA 25V896000 and selects the camera region. The 2025 notice
remains scoped to affected older model years; the 2026 illustration is labeled.
NHTSA 25V079000 similarly maps to a representative lighting-control region.
The 2026 Atlas lookup preserves campaign 25V835000's do-not-drive instruction;
it does not point to a Porsche wheel as an Atlas part. Other notices still show
their official details when a reviewed 3D mapping is absent. Service contact and
the correct dealership action link are provided without inventing a reservation.

**Failed, repaired, retested:** the first embedded recall reply omitted `brand`,
raising a KeyError in the chat handler even though the standalone panel worked.
The response contract, Flask-handler control and real deployment POST check now
cover it. Retained evidence: `recall-chat-before.txt` and `vehicle-browser.json`.

The recall service queries only the supported make/model/year catalog through a
fixed HTTPS NHTSA endpoint, validates vehicle identity and result fields, limits
response size/time and caches responses for ten minutes. An outage uses a dated
saved official response when available. Tests exercise genuine empty results,
wrong-year data, malformed remedy fields, outage, follow-up messages and flags.
These are model-level campaigns; the official manufacturer/VIN check resolves
actual coverage and completion. No owner VIN was submitted during acceptance.

**Blocked:** the official 2026 Porsche 911 recall query returned HTTP 400 while its
catalog lists that model. The demo shows unavailable and retains the official VIN
check. It never labels the failed query as no recalls. Live official Porsche 2025
and Atlas 2026 records were successfully retrieved; raw dated responses are in
`recall-live.json` and `src/demo/data/recall_snapshots.json`.

The supplied research pack was treated as source leads. The [MY2026 announcement](https://newsroom.porsche.com/en_US/2025/products/911-Carrera-4S-Cabriolet-Targa-2026-39921.html),
[2026 technical listing](https://finder.porsche.com/lt/en-LT/details/porsche-911-carrera-4s-new-QVKM62),
[wheel/tire certificate](https://static.nhtsa.gov/odi/tsbs/2026/MC-11033626-0001.pdf)
and [NHTSA API documentation](https://www.nhtsa.gov/nhtsa-datasets-and-apis) were
checked independently. Important corrections: current Porsche configurator pages
display later model-year information; publication in 2026 does not make ASB2 a
2026-vehicle campaign; the supplied Eurospares catalog address redirected to its
home page. No unverified OEM part numbers were promoted into the manifest.

**Blocked:** three public Sketchfab asset-download attempts returned empty HTTP
202 pages rather than usable licensed model archives. Detailed engines found in
search had uncertain variant/rights or were paid older-model assets. No paid asset
was acquired. Exact OEM manufacturing geometry and a complete VIN-specific twin
require a usable authorized source; public dimension tables do not supply them.
`detailed-asset-acquisition.json` records the attempts. The original explanatory
model above was built and tested with the available public facts.

Current checks: **98 Python tests, 10 Node tests**, real Waitress HTTP and a Linux
container running as uid 1000. Python and npm dependency audits report no known
vulnerabilities. Browser scenarios and snapshots are retained with this report.
Earlier-stage exterior observations below retain their original measurements.

The earlier widget answered the owner's best-selling question with an inventory
link. The repository now answers with a reviewed model shortlist and passenger
capacity follow-ups. The demonstration's primary button opens its own interactive
Porsche explorer. The dealership's commercials, inventory filter pages and existing
OEM configurator links are their work; this project did not create them.

## Implemented receiving behavior

- The buying assistant compares seven model references spanning six brands. It
  retains passenger needs from the bounded private conversation and explains
  seating/configuration tradeoffs. It does not infer dealer sales counts, stock
  counts or current prices from manufacturer guides.
- The Carrera 4S visual asset has seven component groups. Direct canvas picking,
  list selection, search, focus, isolation, body-panel hiding, separation and reset
  operate on its actual meshes. Both cameras use the same renderer and raycaster.
- Separation restores assembled transforms before moving leaf meshes, preserves
  scale/orientation, packs projected world bounds in the camera's fixed basis,
  and verifies actual resulting bounds for overlaps and canvas fit. Mobile resizing
  repacks the parts. Reset restores transforms and clears search/selection.
- The connected assistant returns only allowed component IDs and viewer actions.
  The client checks them before changing geometry. The server rejects malformed
  context. Missing engine/gearbox/suspension cutaways produce a truthful answer.
- Texture/decoder loading failures stop readiness, disable controls and expose an
  error. Asset size and SHA256 are checked before parsing. The build verifies the
  source hash, embedded author/license, mesh ownership and repeated-name handling.

## Asset and rights

The unchanged GLB is 4,055,076 bytes, 45 meshes and 652,660 source triangles.
Its embedded author is **Karol Miklas**, with **CC BY-SA 4.0** and the
[original Sketchfab locator](https://sketchfab.com/3d-models/free-porsche-911-carrera-4s-d01b254483794de3819786d93e0e1ebf).
It was obtained from the [official PlayCanvas distribution](https://developer.playcanvas.com/assets/porsche-911-carrera-4s.glb).
The publisher's documentation names a different artist; the exact file's embedded
metadata controls this distribution's attribution. Original-source browsing returned
403 and the public metadata API returned a non-JSON 202; neither was bypassed.
The publisher file and embedded provenance were inspected directly.

SHA256: `421fdabf0da312edb3c22dc0fc915bcc75551ff0db7374a7ebac8af80efc5ea2`.
All 45 mesh indices are accounted for: 44 vehicle surfaces and one presentation
ground plane. The latter is a flat 2.75 × 5.08 source-unit plane and is hidden as
a backdrop, rather than mislabeled as a vehicle part. Indices 42/43 have identical
source names; identity uses mesh indices, not names. Coating and painted body
surfaces remain together. No source geometry was invented or deleted from the GLB.

The model year is absent. This is a Carrera 4S visual reference, not a current
dealer VIN, exact model-year configuration, engineering CAD or inspection record.
The file contains supporting/underbody surfaces, not a detailed engine or full
cabin. The app credits the artist and separates asset share-alike rights from the
MIT application and Three.js and the Apache-licensed Draco decoder. See
[distributed notices](../src/demo/static/models/NOTICE.txt) and
[machine-generated source geometry](evidence/2026-10-04/vehicle-source-geometry.json).

## Observed failures and repairs

| Failed scenario | Verified cause and repair | Retained control |
| --- | --- | --- |
| Owner question, comparison and seven-seat follow-up were link-only/general replies | Inventory branch lacked model facts and a buying-advice path; reviewed guides now answer these cases before the generic inventory handoff | advisor-before.txt; test_advisor.py; actual widget submission |
| Parts labels unreadable and backdrop appeared to be part of the car | Global button text color conflicted with white controls; source ground plane had been grouped with trim | Explicit text color; exhaustive component/ignored-mesh assignment; geometry receipt and screenshots |
| Embedded textures silently failed while viewer said ready | Three.js ImageBitmapLoader fetches blob textures; img-src permission alone did not allow connect-src | Scoped connect-src blob permission, LoadingManager error barrier, captured error logs/failure screenshot and successful container render |
| Typed “rear wheels” selected front wheels | Generic alias “wheels” was matched before the longer “rear wheels” alias | Longest matching alias; rear-wheels-before.txt; regression and actual typed browser retest |
| New answer could scroll directly to citation links | Chat always scrolled to the bottom after an answer | Assistant replies start at answer text; citations use native expandable details; widget browser screenshot |
| Selecting Atlas after a Nissan comparison retained the Nissan showroom | Location routing preceded the chosen model's reviewed store | Model choice updates store and official action links; model-choice-before.txt and typed widget retest |
| Asking for the Porsche explorer retained the earlier seven-passenger filter | A new exploration topic inherited passenger context | Explicit exploration starts that topic; explorer-topic-before.txt and native 3D card click |

These defects escaped earlier checks because those checked HTTP intent/routing and
static page availability without the owner's exact buying flow, complete material
loading or receiving geometry actions. The new regression suites, rebuild/hash gate,
loading barrier and recorded browser scenarios cover those classes.

## Acceptance and reproduction

Windows source verification, the shipped Waitress module and Linux container were
exercised with synthetic questions and zero paid model calls. Desktop and responsive
mobile browser tests exercised actual WebGL geometry and chat controls. Responsive
testing on the desktop is not a physical-phone benchmark.

`scripts/verify.ps1 -Install` installs locked dependencies, builds the viewer, runs
Node/Python controls and actual HTTP acceptance, and audits dependencies.
`scripts/verify_vehicle_deployment.py --base-url http://127.0.0.1:8080 --output vehicle-receipt.json`
tests a running installation's assets and receiving API behavior. Browser checks
are described above and retained separately; HTTP alone does not validate rendering.

The local host advertises AMD Radeon Graphics and NVIDIA RTX 5090; the selected
browser GPU was not queried. Chrome loaded the 4.06 MB asset in 1.7 seconds in one
fresh desktop run and 0.7 seconds on a repeated mobile-size run; the Linux container
render loaded in 0.8 seconds. The assembled render reported 87 draw calls and
1,298,852 rendered triangles, including material passes. Mobile CSS content measured
382 × 844 pixels, with scroll width 382, zero packed overlaps and all projected
parts inside the canvas. These are local observations, not fleet/device guarantees.

The real dealer CMS installation remains blocked by missing CMS access and a
deployed HTTPS service hostname. Its public inventory page was inspected; no
authorized machine-readable current stock/price feed is configured. /health retains
inventory=official_website_links and unconfigured booking/CRM. The new in-chat
model-guide and 3D actions are implemented and tested independently of those
receiving systems. Exact VIN tours need licensed assets/captures for the actual VIN.
