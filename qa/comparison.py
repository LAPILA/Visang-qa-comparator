"""Pixel evidence and region contracts; unknown comparison results are errors."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageOps

from .policy import check


def image_diff(left, right, artifact_root, run_id, key):
    if not left or not right:
        return {'differencePercent': None, 'url': None, 'note': 'Missing capture.', 'error': 'CAPTURE_MISSING'}
    left_path = left.get('screenshotFile') if isinstance(left, dict) else left
    right_path = right.get('screenshotFile') if isinstance(right, dict) else right
    if not left_path or not right_path:
        return {'differencePercent': None, 'url': None, 'note': 'Missing capture.', 'error': 'CAPTURE_MISSING'}
    try:
        with Image.open(left_path) as image_a, Image.open(right_path) as image_b:
            a, b = image_a.convert('RGB'), image_b.convert('RGB')
        if a.size != b.size:
            return {'differencePercent': None, 'url': None, 'note': 'Image dimensions differ.',
                    'error': 'IMAGE_SIZE_MISMATCH', 'sizes': [list(a.size), list(b.size)]}
        delta = ImageChops.difference(a, b).convert('L')
        mask = delta.point(lambda value: 255 if value > 25 else 0)
        excluded = Image.new('L', a.size, 0)
        draw = ImageDraw.Draw(excluded)
        for record in (left, right):
            if not isinstance(record, dict):
                continue
            for box in record.get('maskBoxes', []):
                x, y, width, height = box
                if width > 0 and height > 0:
                    draw.rectangle((max(0, int(x)), max(0, int(y)),
                                    min(a.width - 1, int(x + width - 1)), min(a.height - 1, int(y + height - 1))), fill=255)
        excluded_count = excluded.histogram()[255]
        total = a.width * a.height - excluded_count
        if total <= 0:
            return {'differencePercent': None, 'url': None, 'note': 'No unmasked pixels remain.',
                    'error': 'NO_COMPARABLE_PIXELS', 'maskedPixels': excluded_count}
        mask = ImageChops.subtract(mask, excluded)
        changed = mask.histogram()[255]
        percent = round(changed * 100 / total, 4)
        result = {'differencePercent': percent, 'url': None, 'changedPixels': changed,
                  'totalPixels': a.width * a.height, 'comparedPixels': total,
                  'maskedPixels': excluded_count, 'pixelTolerance': 25}
        if changed:
            overlay = ImageOps.grayscale(a).convert('RGB')
            overlay.paste(Image.new('RGB', a.size, '#e64556'), mask=mask)
            filename = sha256(key.encode('utf-8')).hexdigest()[:20] + '-diff.png'
            folder = Path(artifact_root) / run_id / 'diff'
            folder.mkdir(parents=True, exist_ok=True)
            overlay.save(folder / filename)
            result['url'] = f'/artifacts/{run_id}/diff/{filename}'
        return result
    except Exception as exc:
        return {'differencePercent': None, 'url': None,
                'note': 'Image comparison failed: ' + type(exc).__name__, 'error': 'IMAGE_COMPARE_ERROR'}


def visual_check(visual, threshold, check_id='visual', required=True):
    if not visual or visual.get('differencePercent') is None:
        return check(check_id, 'ERROR', (visual or {}).get('error', 'COMPARISON_UNAVAILABLE'),
                     expected='Comparable image evidence', actual=(visual or {}).get('note'), required=required)
    percent = visual['differencePercent']
    return check(check_id, 'REVIEW' if percent >= threshold else 'PASS',
                 'VISUAL_DIFFERENCE' if percent >= threshold else 'WITHIN_VISUAL_THRESHOLD',
                 expected={'differencePercentBelow': threshold}, actual={'differencePercent': percent},
                 evidence=[visual['url']] if visual.get('url') else [], required=required)
