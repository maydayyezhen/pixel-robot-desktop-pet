from __future__ import annotations

import json
import os
from collections import deque
from pathlib import Path

from PIL import Image, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("ROBOT_CONCEPT_SOURCE", ROOT / "source" / "pixel-robot-pet-concept-v1.png"))
ASSETS = ROOT / "assets"
RUNTIME_ROBOT_HEIGHT = 190
BACKGROUND_DISTANCE_THRESHOLD = 46


def find_main_robot_bbox(image: Image.Image) -> tuple[int, int, int, int]:
    rgb = image.convert("RGB")
    width, height = rgb.size

    # The concept sheet has the production-sized robot in the upper half and
    # action thumbnails below. Limit detection to the upper region.
    y_max = int(height * 0.59)
    pixels = rgb.load()
    foreground = [[False] * width for _ in range(y_max)]

    for y in range(0, y_max):
        for x in range(0, width):
            r, g, b = pixels[x, y]
            lum = (r * 299 + g * 587 + b * 114) // 1000
            saturation_span = max(r, g, b) - min(r, g, b)
            if saturation_span > 18 or lum < 145:
                foreground[y][x] = True

    visited = [[False] * width for _ in range(y_max)]
    best: list[tuple[int, int]] = []

    for start_y in range(y_max):
        for start_x in range(width):
            if visited[start_y][start_x] or not foreground[start_y][start_x]:
                continue
            component: list[tuple[int, int]] = []
            queue: deque[tuple[int, int]] = deque([(start_x, start_y)])
            visited[start_y][start_x] = True
            while queue:
                x, y = queue.popleft()
                component.append((x, y))
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < width and 0 <= ny < y_max and not visited[ny][nx]:
                        visited[ny][nx] = True
                        if foreground[ny][nx]:
                            queue.append((nx, ny))
            if len(component) > len(best):
                best = component

    if not best:
        raise RuntimeError("Could not find robot pixels in the concept image.")

    xs = [p[0] for p in best]
    ys = [p[1] for p in best]
    pad = 30
    return (
        max(0, min(xs) - pad),
        max(0, min(ys) - pad),
        min(width, max(xs) + pad),
        min(height, max(ys) + pad),
    )


def background_mask(crop: Image.Image) -> Image.Image:
    rgb = crop.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()
    visited = [[False] * width for _ in range(height)]
    mask = Image.new("L", (width, height), 0)
    mask_pixels = mask.load()
    queue: deque[tuple[int, int]] = deque()

    def looks_like_backdrop(x: int, y: int) -> bool:
        r, g, b = pixels[x, y]
        lum = (r * 299 + g * 587 + b * 114) // 1000
        saturation_span = max(r, g, b) - min(r, g, b)
        return saturation_span < 26 and 120 <= lum <= 245

    for x in range(width):
        queue.append((x, 0))
        queue.append((x, height - 1))
    for y in range(height):
        queue.append((0, y))
        queue.append((width - 1, y))

    while queue:
        x, y = queue.popleft()
        if x < 0 or y < 0 or x >= width or y >= height or visited[y][x]:
            continue
        visited[y][x] = True
        if not looks_like_backdrop(x, y):
            continue
        mask_pixels[x, y] = 255
        queue.append((x + 1, y))
        queue.append((x - 1, y))
        queue.append((x, y + 1))
        queue.append((x, y - 1))

    return mask


def trim_alpha(image: Image.Image, pad: int = 10) -> Image.Image:
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if not bbox:
        return image
    left, top, right, bottom = bbox
    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(image.width, right + pad)
    bottom = min(image.height, bottom + pad)
    return image.crop((left, top, right, bottom))


def make_transparent_robot(source: Path) -> Image.Image:
    image = Image.open(source).convert("RGBA")
    bbox = find_main_robot_bbox(image)
    crop = image.crop(bbox)

    mask = background_mask(crop).filter(ImageFilter.MaxFilter(3))
    rgba = crop.copy()
    alpha = rgba.getchannel("A")
    alpha_pixels = alpha.load()
    mask_pixels = mask.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            if mask_pixels[x, y] > 0:
                alpha_pixels[x, y] = 0

    rgba.putalpha(alpha)
    return trim_alpha(rgba)


def close_to_color(pixel: tuple[int, int, int, int], color: tuple[int, int, int]) -> bool:
    r, g, b, _a = pixel
    cr, cg, cb = color
    distance = ((r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2) ** 0.5
    return distance <= BACKGROUND_DISTANCE_THRESHOLD


def sampled_background_color(image: Image.Image) -> tuple[int, int, int]:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    samples: list[tuple[int, int, int]] = []
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = pixels[x, y]
            if a == 0 and (x < 8 or y < 8 or x >= rgba.width - 8 or y >= rgba.height - 8):
                samples.append((r, g, b))
    if not samples:
        return (208, 208, 208)
    return tuple(round(sum(channel) / len(samples)) for channel in zip(*samples))


def remove_background_fringe(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = rgba.load()
    bg = sampled_background_color(rgba)

    # Generated concept art often leaves fully opaque gray fringe pixels at the
    # cutout edge. Flood from transparent pixels into only background-like edge
    # pixels so the robot body and dark outline stay intact.
    queue: deque[tuple[int, int]] = deque()
    visited = [[False] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            if pixels[x, y][3] == 0:
                queue.append((x, y))
                visited[y][x] = True

    to_clear: set[tuple[int, int]] = set()
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if nx < 0 or ny < 0 or nx >= width or ny >= height or visited[ny][nx]:
                continue
            visited[ny][nx] = True
            if pixels[nx, ny][3] == 0 or close_to_color(pixels[nx, ny], bg):
                to_clear.add((nx, ny))
                queue.append((nx, ny))

    for x, y in to_clear:
        r, g, b, _a = pixels[x, y]
        pixels[x, y] = (r, g, b, 0)

    return trim_alpha(rgba, pad=8)


def largest_dark_component_bbox(image: Image.Image) -> tuple[int, int, int, int]:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    width, height = rgba.size
    visited = [[False] * width for _ in range(height)]
    best: list[tuple[int, int]] = []

    def is_dark_subject(x: int, y: int) -> bool:
        r, g, b, a = pixels[x, y]
        if a < 20:
            return False
        lum = (r * 299 + g * 587 + b * 114) // 1000
        return lum < 70

    for start_y in range(height):
        for start_x in range(width):
            if visited[start_y][start_x] or not is_dark_subject(start_x, start_y):
                continue
            component: list[tuple[int, int]] = []
            queue: deque[tuple[int, int]] = deque([(start_x, start_y)])
            visited[start_y][start_x] = True
            while queue:
                x, y = queue.popleft()
                component.append((x, y))
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < width and 0 <= ny < height and not visited[ny][nx]:
                        visited[ny][nx] = True
                        if is_dark_subject(nx, ny):
                            queue.append((nx, ny))
            if len(component) > len(best):
                best = component

    if not best:
        return (0, 0, width, height)

    xs = [p[0] for p in best]
    ys = [p[1] for p in best]
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1)


def resize_to_height(
    image: Image.Image,
    height: int,
    resampling: Image.Resampling = Image.Resampling.LANCZOS,
) -> Image.Image:
    width = round(image.width * (height / image.height))
    return hard_alpha(image.resize((width, height), resampling))


def hard_alpha(image: Image.Image, threshold: int = 112) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = pixels[x, y]
            pixels[x, y] = (r, g, b, 255 if a >= threshold else 0)
    return rgba


def main() -> None:
    if not SOURCE.exists():
        raise FileNotFoundError(
            f"Source concept image not found: {SOURCE}. "
            "Set ROBOT_CONCEPT_SOURCE to regenerate assets from a different local source image."
        )

    ASSETS.mkdir(parents=True, exist_ok=True)
    robot_raw = make_transparent_robot(SOURCE)
    robot_raw_path = ASSETS / "robot-source-cutout.png"
    robot_raw.save(robot_raw_path)

    robot = remove_background_fringe(robot_raw)
    robot_master_path = ASSETS / "robot-master-refined.png"
    robot.save(robot_master_path)

    runtime_robot = resize_to_height(robot, RUNTIME_ROBOT_HEIGHT)
    robot_path = ASSETS / "robot.png"
    runtime_robot.save(robot_path)

    master_screen_bbox = largest_dark_component_bbox(robot)
    screen_bbox = largest_dark_component_bbox(runtime_robot)
    metadata = {
        "source": str(SOURCE.relative_to(ROOT)) if SOURCE.is_relative_to(ROOT) else "",
        "robot_source_cutout": str(robot_raw_path.relative_to(ROOT)).replace("\\", "/"),
        "robot_master_refined": str(robot_master_path.relative_to(ROOT)).replace("\\", "/"),
        "robot": str(robot_path.relative_to(ROOT)).replace("\\", "/"),
        "master_screen_bbox": master_screen_bbox,
        "master_size": robot.size,
        "screen_bbox": screen_bbox,
        "robot_size": runtime_robot.size,
    }
    (ASSETS / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
