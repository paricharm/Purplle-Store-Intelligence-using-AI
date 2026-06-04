# CCTV Person Annotation Protocol

Use this protocol for the Roboflow dataset that trains `models/best.pt`.

## Goal

Train a reliable person detector for retail CCTV footage. The YOLO model should detect every visible human body so the downstream pipeline can track movement, infer entry/exit, map people to zones, and compute business metrics.

The primary YOLO class should be:

```text
person
```

Do not train separate YOLO classes for `customer`, `staff`, `queue`, `entry`, or product zones in the first model. Staff detection, zone mapping, queue depth, and re-entry are downstream logic in this project.

## What To Label

Label as `person`:

- Every visible customer.
- Every visible staff member.
- People partially visible through occlusion when at least the head/torso or roughly 30% of the body is visible.
- People entering in groups, with one separate box per person.
- People in the billing queue, even when boxes overlap.
- People seen from the back, side, top angle, or with face blur.

Do not label:

- Posters, mannequins, reflections, product images, or screen images.
- Hands only, feet only, or tiny body fragments.
- People almost completely hidden where the model cannot learn a stable visual pattern.
- Shopping bags, counters, shelves, baskets, or product stands.

## Bounding Box Rules

- Draw a tight box around the visible body area.
- Include the blurred face/head if it is visible.
- Include visible limbs when they belong clearly to the person.
- If the lower body is hidden behind a counter/shelf, box only the visible body region.
- If two people overlap, draw two boxes around the visible parts of each person.
- Do not draw one large box around a group.
- Keep boxes inside the image boundary.

## Negative Frames

Keep some frames with no people and no boxes. These help reduce false positives in empty-store periods. In Roboflow, mark them as images with zero annotations rather than deleting all empty scenes.

Recommended mix:

- 70-80% frames with people.
- 20-30% empty or near-empty frames.

## Edge Case Coverage

Make sure the dataset includes:

- Entry/exit threshold frames.
- Group entry with 2-4 people.
- Staff moving across customer zones.
- Billing queue buildup.
- Billing crowd overlap.
- Empty store periods.
- Partial occlusion behind shelves or other customers.
- Lighting changes across the CCTV clips.
- Each camera angle, not only the clearest one.

## Dataset Size Target

For a challenge-quality model:

- Minimum: 250-400 labeled frames.
- Better: 600-1,200 labeled frames across all cameras.
- Aim for at least 50-100 examples of occlusion and queue scenes.

Avoid labeling thousands of near-identical consecutive frames. Use diverse frames from different timestamps and cameras.

## Split Strategy

Use a split that avoids near-duplicate leakage:

- Train: 70%
- Validation: 20%
- Test: 10%

Prefer splitting by time chunk or camera clip segment rather than pure random frame split. Consecutive frames are almost identical, so random splitting can make validation look better than the model really is.

## Roboflow Settings

Project type:

```text
Object Detection
```

Class list:

```text
person
```

Recommended preprocessing:

- Auto-orient: enabled.
- Resize: 640x640.
- Use letterbox/fit behavior if available so people are not distorted.

Recommended augmentations:

- Brightness/exposure: small variation.
- Blur/noise: light variation.
- Horizontal flip: acceptable for person detection.
- Mosaic: optional and moderate.

Avoid:

- Vertical flip.
- Extreme rotations.
- Heavy crops that remove most of the person.
- Strong color transformations that no longer look like CCTV.

## Review Checklist

Before generating a Roboflow dataset version:

- Every visible person has exactly one `person` box.
- No group boxes.
- Staff are labeled as `person`.
- Empty frames are kept as empty labels.
- Boxes are tight and not much larger than the body.
- Crowded billing frames are reviewed manually.
- Validation/test sets contain camera angles and edge cases not overrepresented in train.

## Training Usage

After annotation:

1. In Roboflow, create a dataset version.
2. Export/download in YOLOv8 format.
3. In `notebooks/train_yolo_colab.ipynb`, set `USE_ROBOFLOW = True`.
4. Fill `ROBOFLOW_WORKSPACE`, `ROBOFLOW_PROJECT`, and `ROBOFLOW_VERSION`.
5. Run the notebook training cells.
6. Download the saved `best.pt`.
7. Place it at `models/best.pt`.

Then run:

```bash
python -m pipeline.run --mode detect --video "CCTV Footage/CAM 1.mp4" --camera-id CAM_1 --model models/best.pt --output generated_events.jsonl
```
