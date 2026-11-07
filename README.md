# BoxTurtles

The public detection website lives in [`dashboard/`](dashboard/README.md): real `best.pt` inference, image/video uploads, persisted jobs, gallery, GPS map and Linux/Docker deployment. The original local demo remains available as a separate legacy mode.

## AI-Powered Eastern Box Turtle Detection

BoxTurtles is a computer vision project focused on identifying Eastern Box Turtles (*Terrapene carolina*) using AI-powered object detection.

Our goal is to help protect turtles on construction sites by eventually using drone imagery to locate turtles before land clearing begins, allowing people to safely relocate them.

## How It Works

We developed an object detection model using YOLO26s.

Our training process included:

1. Collecting 500 research-grade box turtle images from iNaturalist.
2. Annotating images using Roboflow.
3. Converting polygon annotations into bounding boxes.
4. Training an initial model (turtle1).
5. Adding approximately 200 turtle-free images as negative examples to reduce false positives.
6. Training an improved model (turtle2).

## Model Results

Our current model, turtle2, produced the following results:

| Evaluation | Result |
|---|---|
| Test turtles detected | 48 / 50 |
| Held-out negative images incorrectly flagged | 1 / 72 |
| Working confidence threshold | 0.5 |
| Model | YOLO26s |
| Image size | 640 |

These results are from ground-level photographs, not aerial imagery.

## Technologies Used

- Python
- YOLO26s
- Ultralytics
- Kaggle Notebooks
- Roboflow
- iNaturalist

## Repository Contents

- `challenge-x.ipynb` – Kaggle notebook containing the model training and evaluation workflow.

## Current Limitations

The model has not yet been evaluated on aerial or drone imagery. Its performance at different flight heights remains unknown.

## Future Work

- Collect aerial photographs at different heights.
- Evaluate detection accuracy from above.
- Retrain the model using aerial imagery.
- Test with actual drone footage.
- Evaluate coverage and detection performance for wildlife monitoring.

## Dataset

The annotated dataset is privately hosted on Kaggle and is not included in this repository.

## Project Status

<em>Active development – currently transitioning from ground-level detection to aerial detection.</em>

## Turtle Survey Dashboard

The [dashboard](dashboard/README.md) adds a local website for reviewing turtle detections from uploaded photographs, recorded DJI Avata 2 footage, and sampled frames from a browser-shared scrcpy window. Its **Asian Baddies** interface includes light/dark themes, adjustable thumbnails and list view, previous/next image inspection, bulk review, confirmed deletion of rejected photos, verified sightings, maps, and replaceable local YOLO adapters.

Demo mode works without a model file, drone or paid API. The live workspace previews your shared scrcpy window and can run the selected model on sampled frames. Its **Live YOLO** page continuously annotates analyzed frames with boxes and confidence scores, with actual throughput/latency readings and optional candidate-frame saving. Both live pages retain the same window share and in-memory ingestion token.

Optional automatic acceptance sends new genuine local YOLO turtle predictions at or above a configured confidence threshold to Verified sightings, with the method and threshold recorded; it starts off, excludes demo/upstream results, and leaves existing reviews unchanged. Live snapshots retain their measured browser capture time and its provenance; missing GPS stays unknown. Actual DJI capture quality and the model's aerial accuracy still require field verification.

The launcher recognizes an already-running dashboard instead of starting another server on port 8000. See the [dashboard guide](dashboard/README.md) for photo management, live-feed setup, and backend restart instructions.

After cloning this repository, open `dashboard/` and follow its [Windows/Linux installation instructions](dashboard/README.md#fresh-installation-windows). Use Python 3.11/3.12 and Node.js 22.12 or newer; dependencies and runtime data are not committed. The original training notebook remains at the repository root.
