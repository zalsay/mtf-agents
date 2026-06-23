#!/usr/bin/env python3
"""Generate a vertical cover image from a HyperFrames/H5 page or rendered MP4.

The script prefers decoding a frame from the rendered MP4 with Python, then
overlays a large two-line yellow watermark with Pillow. It falls back to a
Playwright page capture only when no rendered MP4 is available.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
from PIL import Image, ImageDraw, ImageFilter, ImageFont


FONT_CANDIDATES: tuple[str, ...] = (
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
)


@dataclass(frozen=True)
class CoverConfig:
    input_media: Path
    output_png: Path
    page_selector: str
    line1: str
    line2: str
    width: int
    height: int
    background_color: str
    frame_time_seconds: float


def parse_args() -> CoverConfig:
    parser = argparse.ArgumentParser(description="Generate a daily video cover.")
    parser.add_argument("--input-media", "--input-html", dest="input_media", required=True, type=Path, help="Rendered MP4 or H5/HyperFrames HTML file")
    parser.add_argument("--output", required=True, type=Path, help="Output PNG path")
    parser.add_argument("--page-selector", default="#page-04", help="CSS selector for the source page")
    parser.add_argument("--line1", default="AI 新技能", help="First line of the watermark")
    parser.add_argument("--line2", default="第 4 天", help="Second line of the watermark")
    parser.add_argument("--width", type=int, default=1080, help="Output width")
    parser.add_argument("--height", type=int, default=1920, help="Output height")
    parser.add_argument("--background-color", default="#03070d", help="Fallback background color")
    parser.add_argument("--frame-time-seconds", type=float, default=80.0, help="Video timestamp to sample when using MP4")
    args = parser.parse_args()
    return CoverConfig(
        input_media=args.input_media,
        output_png=args.output,
        page_selector=args.page_selector,
        line1=args.line1,
        line2=args.line2,
        width=args.width,
        height=args.height,
        background_color=args.background_color,
        frame_time_seconds=args.frame_time_seconds,
    )


def find_font() -> str:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise FileNotFoundError(
        "No usable Chinese font found. Looked for: " + ", ".join(FONT_CANDIDATES)
    )


def _find_video_source(media_path: Path) -> Path | None:
    if media_path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}:
        return media_path

    search_dirs = [media_path.parent, media_path.parent / "hyperframes"]
    candidates: list[Path] = []
    for directory in search_dirs:
        if not directory.exists():
            continue
        candidates.extend(sorted(directory.glob("*narrated-h265.mp4")))
        candidates.extend(sorted(directory.glob("*silent-h265.mp4")))
        candidates.extend(sorted(directory.glob("*.mp4")))
    # Prefer the narrated final render, then any rendered mp4.
    unique_candidates: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate not in seen and candidate.exists():
            unique_candidates.append(candidate)
            seen.add(candidate)
    return unique_candidates[0] if unique_candidates else None


def _page_four_timestamp(hyperframes_index: Path | None, fallback: float) -> float:
    if not hyperframes_index or not hyperframes_index.exists():
        return fallback
    try:
        text = hyperframes_index.read_text(encoding="utf-8")
    except Exception:
        return fallback
    matches = re.findall(r"\{\s*start:\s*([0-9.]+),\s*duration:\s*([0-9.]+)\s*\}", text)
    if len(matches) < 4:
        return fallback
    start_str, duration_str = matches[3]
    start = float(start_str)
    duration = float(duration_str)
    # Capture after the page has mostly settled so the page is fully legible.
    return start + max(3.0, min(duration * 0.6, max(duration - 1.0, 3.0)))


def _fit_font(draw: ImageDraw.ImageDraw, text: str, font_path: str, target_width: int, start_size: int) -> ImageFont.FreeTypeFont:
    size = start_size
    while size >= 24:
        font = ImageFont.truetype(font_path, size=size)
        bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=max(10, size // 5), stroke_width=max(6, size // 18))
        text_width = bbox[2] - bbox[0]
        if text_width <= target_width:
            return font
        size -= 4
    return ImageFont.truetype(font_path, size=24)


def _compose_cover(base: Image.Image, line1: str, line2: str, output_size: tuple[int, int]) -> Image.Image:
    if base.mode != "RGBA":
        base = base.convert("RGBA")
    if base.size != output_size:
        base = base.resize(output_size, Image.Resampling.LANCZOS)

    overlay = Image.new("RGBA", output_size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font_path = find_font()
    font = _fit_font(draw, f"{line1}\n{line2}", font_path, target_width=int(output_size[0] * 0.74), start_size=148)
    stroke = max(8, font.size // 16)
    spacing = max(8, font.size // 5)
    bbox = draw.multiline_textbbox((0, 0), f"{line1}\n{line2}", font=font, spacing=spacing, stroke_width=stroke, align="center")
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    center_x = output_size[0] // 2
    center_y = int(output_size[1] * 0.78)
    x = center_x - text_w // 2
    y = center_y - text_h // 2

    shadow = Image.new("RGBA", output_size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.multiline_text(
        (x + 14, y + 16),
        f"{line1}\n{line2}",
        font=font,
        fill=(0, 0, 0, 235),
        spacing=spacing,
        align="center",
        stroke_width=stroke,
        stroke_fill=(0, 0, 0, 220),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(4, font.size // 14)))

    draw.multiline_text(
        (x, y),
        f"{line1}\n{line2}",
        font=font,
        fill=(255, 212, 77, 255),
        spacing=spacing,
        align="center",
        stroke_width=stroke,
        stroke_fill=(24, 18, 6, 255),
    )

    result = Image.alpha_composite(base, shadow)
    result = Image.alpha_composite(result, overlay)
    return result


async def _capture_page(config: CoverConfig, screenshot_path: Path) -> None:
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "playwright is required. Use the workspace Python environment with the bundled package."
        ) from exc

    html_url = config.input_media.resolve().as_uri()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": config.width, "height": config.height},
            device_scale_factor=2,
        )
        page = await context.new_page()
        await page.goto(html_url, wait_until="networkidle")
        await page.add_style_tag(
            content="""
              .page-shell, .fade-block {
                opacity: 1 !important;
                transform: none !important;
                animation: none !important;
                transition: none !important;
              }
              html, body {
                scroll-behavior: auto !important;
              }
            """
        )
        await page.evaluate(
            """
            (selector) => {
              const pages = Array.from(document.querySelectorAll('.page'));
              pages.forEach((page) => {
                page.style.display = 'none';
                page.style.visibility = 'hidden';
              });
              const target = document.querySelector(selector);
              if (!target) {
                throw new Error(`Target page not found: ${selector}`);
              }
              target.style.display = 'block';
              target.style.visibility = 'visible';
              target.style.position = 'relative';
              target.style.inset = 'auto';
            }
            """,
            config.page_selector,
        )
        page_loc = page.locator(config.page_selector)
        await page_loc.wait_for(state="visible")
        await page.wait_for_timeout(250)
        await page_loc.screenshot(path=str(screenshot_path))
        await context.close()
        await browser.close()


def _capture_frame_from_video(video_path: Path, timestamp_seconds: float, output_path: Path) -> None:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Unable to open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 1e-6:
        fps = 25.0
    frame_index = max(0, int(round(timestamp_seconds * fps)))
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = cap.read()
    if not ok or frame is None:
        # Retry a few frames around the target index.
        for delta in (1, -1, 2, -2, 5, -5, 10, -10):
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_index + delta))
            ok, frame = cap.read()
            if ok and frame is not None:
                break
    cap.release()
    if not ok or frame is None:
        raise RuntimeError(f"Unable to decode frame at {timestamp_seconds:.2f}s from {video_path}")
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    Image.fromarray(rgb).save(output_path)


def generate_cover(config: CoverConfig) -> Path:
    config.output_png.parent.mkdir(parents=True, exist_ok=True)
    base_png = config.output_png.with_suffix(".base.png")
    try:
        video_source = _find_video_source(config.input_media)
        if video_source is not None:
            hyperframes_index = config.input_media.parent / "hyperframes" / "index.html"
            timestamp = _page_four_timestamp(hyperframes_index, config.frame_time_seconds)
            _capture_frame_from_video(video_source, timestamp, base_png)
        else:
            asyncio.run(_capture_page(config, base_png))
        with Image.open(base_png) as base:
            cover = _compose_cover(base, config.line1, config.line2, (config.width, config.height))
            cover.save(config.output_png)
    finally:
        if base_png.exists():
            base_png.unlink()
    return config.output_png


def main() -> int:
    config = parse_args()
    if not config.input_media.exists():
        print(f"input media not found: {config.input_media}", file=sys.stderr)
        return 2
    output = generate_cover(config)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
