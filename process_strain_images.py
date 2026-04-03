import argparse
import datetime
import os
import tkinter as tk
from tkinter import messagebox
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk


PROJECT_DIR = r"d:\2026.03 FLAC3D Code-Native"
PROJECT_NAME = "longrong3_after_treatment_relia_100sim"
PLOTS_SUBDIR = "plots"
OUTPUT_TAG = "displacement"
SCALAR_MIN = 0.0
SCALAR_MAX = 0.5
THRESHOLD_LEVEL_COUNT = 5
PROBABILITY_DISPLAY_GAMMA = 0.35
DEFAULT_COLORMAP = "turbo"


def collect_image_files(input_dir):
    if not os.path.exists(input_dir):
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    image_files = sorted(
        f for f in os.listdir(input_dir)
        if f.startswith("strain_increment") and f.endswith(".png")
    )
    if not image_files:
        raise FileNotFoundError("No strain_increment images found.")
    return image_files


def parse_roi_text(roi_text):
    values = [int(v.strip()) for v in roi_text.split(",")]
    if len(values) != 4:
        raise ValueError("ROI must contain four integers: x1,y1,x2,y2")
    x1, y1, x2, y2 = values
    if x2 <= x1 or y2 <= y1:
        raise ValueError("ROI must satisfy x2>x1 and y2>y1")
    return x1, y1, x2, y2


def select_roi(image):
    root = tk.Tk()
    root.title("Select slope body ROI")

    max_width = 1400
    max_height = 900
    scale = min(max_width / image.width, max_height / image.height, 1.0)
    display_size = (int(image.width * scale), int(image.height * scale))
    display_image = image.resize(display_size, Image.Resampling.LANCZOS)
    tk_image = ImageTk.PhotoImage(display_image)

    canvas = tk.Canvas(root, width=display_size[0], height=display_size[1], cursor="cross")
    canvas.pack()
    canvas.create_image(0, 0, anchor="nw", image=tk_image)

    state = {"start": None, "rect": None, "roi": None}

    def on_press(event):
        state["start"] = (event.x, event.y)
        if state["rect"] is not None:
            canvas.delete(state["rect"])
            state["rect"] = None

    def on_drag(event):
        if state["start"] is None:
            return
        x1, y1 = state["start"]
        x2, y2 = event.x, event.y
        if state["rect"] is not None:
            canvas.coords(state["rect"], x1, y1, x2, y2)
        else:
            state["rect"] = canvas.create_rectangle(x1, y1, x2, y2, outline="red", width=2)

    def on_release(event):
        if state["start"] is None:
            return
        x1, y1 = state["start"]
        x2, y2 = event.x, event.y
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        if x2 - x1 < 5 or y2 - y1 < 5:
            state["roi"] = None
            return
        state["roi"] = (
            int(round(x1 / scale)),
            int(round(y1 / scale)),
            int(round(x2 / scale)),
            int(round(y2 / scale)),
        )

    def confirm():
        if state["roi"] is None:
            messagebox.showwarning("ROI", "Please drag a rectangle around the slope body.")
            return
        root.destroy()

    def cancel():
        state["roi"] = None
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)

    controls = tk.Frame(root)
    controls.pack(fill="x")
    tk.Label(controls, text="Drag to crop only the geological body area, then click Confirm").pack(side="left", padx=8, pady=6)
    tk.Button(controls, text="Confirm", command=confirm).pack(side="right", padx=8, pady=6)
    tk.Button(controls, text="Cancel", command=cancel).pack(side="right", pady=6)

    root.mainloop()
    return state["roi"]


def crop_array(array, roi):
    x1, y1, x2, y2 = roi
    return array[y1:y2, x1:x2]


def detect_colorbar(full_array):
    search = full_array[:, : max(1, int(full_array.shape[1] * 0.28)), :]
    blue_metric = search[:, :, 2].astype(np.float32) - 0.5 * (
        search[:, :, 0].astype(np.float32) + search[:, :, 1].astype(np.float32)
    )
    mask = (blue_metric > 12.0) & (search[:, :, 2] > 70)
    ys, xs = np.where(mask)
    if ys.size == 0:
        raise RuntimeError("Colorbar not detected. Please provide a sample image with the legend visible.")
    x1, x2 = int(xs.min()), int(xs.max()) + 1
    y1, y2 = int(ys.min()), int(ys.max()) + 1
    return x1, y1, x2, y2


def build_scalar_mapper(full_array, scalar_min, scalar_max):
    x1, y1, x2, y2 = detect_colorbar(full_array)
    bar = full_array[y1:y2, x1:x2, :].astype(np.float32)
    bar_metric = bar[:, :, 2] - 0.5 * (bar[:, :, 0] + bar[:, :, 1])
    blue_mask = (bar_metric > 12.0) & (bar[:, :, 2] > 70)

    row_metric = np.full(bar.shape[0], -np.inf, dtype=np.float32)
    row_rgb = np.zeros((bar.shape[0], 3), dtype=np.float32)

    for idx in range(bar.shape[0]):
        row_mask = blue_mask[idx]
        if np.any(row_mask):
            row_metric[idx] = float(np.percentile(bar_metric[idx][row_mask], 90))
            row_rgb[idx] = np.mean(bar[idx][row_mask], axis=0)

    valid_rows = np.isfinite(row_metric)
    if np.count_nonzero(valid_rows) < 2:
        raise RuntimeError("Colorbar detection is too weak. Please provide an image with a clearer legend.")

    valid_indices = np.where(valid_rows)[0]
    high_idx = valid_indices[np.argmax(row_metric[valid_rows])]
    low_idx = valid_indices[np.argmin(row_metric[valid_rows])]
    high_metric = float(row_metric[high_idx])
    low_metric = float(row_metric[low_idx])

    if high_metric - low_metric < 1e-6:
        raise RuntimeError(
            f"Invalid colorbar metric range: high={high_metric:.4f}, low={low_metric:.4f}."
        )

    peak_blue = np.clip(row_rgb[high_idx], 0, 255).astype(np.uint8)

    def mapper(rgb_array):
        rgb = rgb_array.astype(np.float32)
        metric = rgb[:, :, 2] - 0.5 * (rgb[:, :, 0] + rgb[:, :, 1])
        normalized = np.clip((metric - low_metric) / (high_metric - low_metric), 0.0, 1.0)
        scalar = scalar_min + normalized * (scalar_max - scalar_min)
        return scalar, normalized

    return mapper, peak_blue


def interpolate_colormap(value, stops):
    value = float(np.clip(value, 0.0, 1.0))
    for (p0, c0), (p1, c1) in zip(stops[:-1], stops[1:]):
        if value <= p1:
            t = 0.0 if p1 <= p0 else (value - p0) / (p1 - p0)
            c0 = np.asarray(c0, dtype=np.float32)
            c1 = np.asarray(c1, dtype=np.float32)
            return (c0 * (1.0 - t) + c1 * t).astype(np.float32)
    return np.asarray(stops[-1][1], dtype=np.float32)


def get_colormap_color(value, colormap_name, peak_blue):
    peak = tuple(int(v) for v in peak_blue.tolist())
    colormaps = {
        "blue": [
            (0.0, (255, 255, 255)),
            (0.25, (220, 223, 245)),
            (0.5, (166, 176, 232)),
            (0.75, (92, 103, 206)),
            (1.0, peak),
        ],
        "turbo": [
            (0.0, (48, 18, 59)),
            (0.2, (50, 97, 223)),
            (0.4, (30, 177, 236)),
            (0.6, (102, 219, 88)),
            (0.8, (252, 214, 63)),
            (1.0, (180, 4, 38)),
        ],
        "viridis": [
            (0.0, (68, 1, 84)),
            (0.25, (59, 82, 139)),
            (0.5, (33, 145, 140)),
            (0.75, (94, 201, 97)),
            (1.0, (253, 231, 37)),
        ],
        "magma": [
            (0.0, (0, 0, 4)),
            (0.25, (84, 15, 109)),
            (0.5, (187, 55, 84)),
            (0.75, (249, 142, 8)),
            (1.0, (252, 253, 191)),
        ],
        "inferno": [
            (0.0, (0, 0, 4)),
            (0.25, (87, 15, 109)),
            (0.5, (187, 55, 84)),
            (0.75, (249, 142, 8)),
            (1.0, (252, 255, 164)),
        ],
    }
    if colormap_name not in colormaps:
        raise ValueError(f"Unsupported colormap: {colormap_name}")
    return interpolate_colormap(value, colormaps[colormap_name])


def build_colormap_image(probability, colormap_name, peak_blue, gamma):
    display_probability = np.power(np.clip(probability, 0.0, 1.0), gamma)
    height, width = probability.shape
    image = np.zeros((height, width, 3), dtype=np.float32)
    for y in range(height):
        for x in range(width):
            image[y, x] = get_colormap_color(display_probability[y, x], colormap_name, peak_blue)
    return image, display_probability


def add_probability_labels(image_array, probability):
    image = Image.fromarray(np.clip(image_array, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    selected_points = []
    targets = (0.2, 0.4, 0.6, 0.8)

    for target in targets:
        mask = probability > 0.0
        if not np.any(mask):
            continue
        diff = np.full(probability.shape, np.inf, dtype=np.float32)
        diff[mask] = np.abs(probability[mask] - target)
        y, x = np.unravel_index(np.argmin(diff), diff.shape)
        if not np.isfinite(diff[y, x]) or diff[y, x] > 0.08:
            continue
        if any((x - px) ** 2 + (y - py) ** 2 < 40 ** 2 for px, py in selected_points):
            continue
        label = f"{int(round(probability[y, x] * 100.0))}%"
        selected_points.append((x, y))
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=(255, 255, 255), outline=(0, 0, 0))
        bbox = draw.textbbox((x + 8, y - 10), label, font=font)
        draw.rectangle(bbox, fill=(255, 255, 255))
        draw.text((x + 8, y - 10), label, fill=(0, 0, 0), font=font)

    return np.array(image)


def render_probability_overlay(base_rgb, probability, peak_blue, gamma, colormap_name):
    base_gray = np.mean(base_rgb.astype(np.float32), axis=2, keepdims=True)
    base_gray_rgb = np.repeat(base_gray, 3, axis=2)
    color, display_probability = build_colormap_image(probability, colormap_name, peak_blue, gamma)
    probability_3d = display_probability[:, :, None]
    alpha = np.where(probability_3d > 0.0, 0.20 + 0.75 * probability_3d, 0.0)
    overlay = base_gray_rgb * (1.0 - alpha) + color * alpha
    return add_probability_labels(np.clip(overlay, 0, 255).astype(np.uint8), probability)


def render_probability_scalar(probability, peak_blue, gamma, colormap_name):
    scalar_img, _ = build_colormap_image(probability, colormap_name, peak_blue, gamma)
    return add_probability_labels(np.clip(scalar_img, 0, 255).astype(np.uint8), probability)


def format_threshold_suffix(value):
    return f"{value:.3f}".replace(".", "p")


def format_run_suffix():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def process_images(scalar_min, scalar_max, roi=None, probability_gamma=PROBABILITY_DISPLAY_GAMMA,
                   colormap_name=DEFAULT_COLORMAP):
    project_root = os.path.join(PROJECT_DIR, "data", PROJECT_NAME)
    input_dir = os.path.join(project_root, PLOTS_SUBDIR)
    run_suffix = format_run_suffix()
    output_dir = os.path.join(project_root, f"failure_probability_outputs-{OUTPUT_TAG}-{colormap_name}-{run_suffix}")
    os.makedirs(output_dir, exist_ok=True)

    image_files = collect_image_files(input_dir)
    print(f"Found {len(image_files)} images. Processing...")

    first_image = Image.open(os.path.join(input_dir, image_files[0])).convert("RGB")
    first_array = np.array(first_image)

    if roi is None:
        roi = select_roi(first_image)
        if roi is None:
            print("Cancelled.")
            return

    mapper, peak_blue = build_scalar_mapper(first_array, scalar_min, scalar_max)
    first_crop = crop_array(first_array, roi)
    first_scalar, _ = mapper(first_crop)

    threshold_values = np.linspace(scalar_min, scalar_max, THRESHOLD_LEVEL_COUNT)
    exceed_counts = [np.zeros(first_scalar.shape, dtype=np.float32) for _ in threshold_values]
    min_blend = np.full(first_crop.shape, 255, dtype=np.uint8)

    processed = 0
    for image_file in image_files:
        image_path = os.path.join(input_dir, image_file)
        array = np.array(Image.open(image_path).convert("RGB"))
        crop = crop_array(array, roi)
        scalar_map, _ = mapper(crop)
        for idx, threshold in enumerate(threshold_values):
            exceed_counts[idx][scalar_map >= threshold] += 1.0
        min_blend = np.minimum(min_blend, crop)
        processed += 1
        if processed % 10 == 0 or processed == len(image_files):
            print(f"  Processed {processed}/{len(image_files)}...")

    for idx, threshold in enumerate(threshold_values):
        probability = exceed_counts[idx] / float(len(image_files))
        overlay_image = render_probability_overlay(min_blend, probability, peak_blue, probability_gamma, colormap_name)
        scalar_image = render_probability_scalar(probability, peak_blue, probability_gamma, colormap_name)
        threshold_suffix = format_threshold_suffix(threshold)
        output_heatmap = os.path.join(
            output_dir,
            f"failure_probability_heatmap-{OUTPUT_TAG}-thr_{threshold_suffix}.png"
        )
        output_scalar = os.path.join(
            output_dir,
            f"failure_probability_scalar-{OUTPUT_TAG}-thr_{threshold_suffix}.png"
        )
        output_probability = os.path.join(
            output_dir,
            f"failure_probability-{OUTPUT_TAG}-thr_{threshold_suffix}.npy"
        )
        Image.fromarray(overlay_image).save(output_heatmap)
        Image.fromarray(scalar_image).save(output_scalar)
        np.save(output_probability, probability)
        print(f"Saved probability overlay to: {output_heatmap}")
        print(f"Saved scalar probability map to: {output_scalar}")
        print(f"Saved raw probability array to: {output_probability}")

    output_composite = os.path.join(output_dir, f"failure_zone_composite-{OUTPUT_TAG}.png")
    Image.fromarray(min_blend).save(output_composite)
    print(f"Saved exceedance composite to: {output_composite}")
    print(f"Output directory: {output_dir}")
    print(f"Thresholds used: {[float(v) for v in threshold_values]}")
    print(f"ROI used: {roi}")
    print(f"Scalar range used: [{scalar_min}, {scalar_max}]")
    print(f"Probability display gamma: {probability_gamma}")
    print(f"Colormap used: {colormap_name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scalar-min", type=float, default=SCALAR_MIN)
    parser.add_argument("--scalar-max", type=float, default=SCALAR_MAX)
    parser.add_argument("--roi", type=str, default=None)
    parser.add_argument("--probability-gamma", type=float, default=PROBABILITY_DISPLAY_GAMMA)
    parser.add_argument(
        "--colormap",
        type=str,
        default=DEFAULT_COLORMAP,
        choices=["blue", "turbo", "viridis", "magma", "inferno"]
    )
    args = parser.parse_args()

    roi = parse_roi_text(args.roi) if args.roi else None
    process_images(
        args.scalar_min,
        args.scalar_max,
        roi=roi,
        probability_gamma=args.probability_gamma,
        colormap_name=args.colormap,
    )


if __name__ == "__main__":
    main()
