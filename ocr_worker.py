import json
import os
import sys
import tempfile


def extract_text_lines(result: object) -> list[str]:
    lines: list[str] = []

    if not isinstance(result, list):
        return lines

    for page in result:
        if isinstance(page, dict):
            for text in page.get('rec_texts', []) or []:
                if text:
                    lines.append(str(text))
            continue

        if not isinstance(page, list):
            continue

        for item in page:
            if isinstance(item, dict):
                text = item.get('text') or item.get('rec_text') or ''
                if text:
                    lines.append(str(text))
                continue

            if (
                isinstance(item, (list, tuple))
                and len(item) > 1
                and isinstance(item[1], (list, tuple))
                and len(item[1]) > 0
            ):
                text = item[1][0]
                if text:
                    lines.append(str(text))

    return lines


def dedupe_lines(lines: list[str]) -> list[str]:
    seen = set()
    unique = []
    for line in lines:
        key = ' '.join(line.split()).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(line)
    return unique


def run_ocr_call(ocr, image_path: str, use_cls: bool):
    try:
        if use_cls:
            return ocr.ocr(image_path, cls=True)
        return ocr.ocr(image_path)
    except TypeError:
        return ocr.ocr(image_path)


def build_candidate_paths(image_path: str) -> tuple[list[str], list[str]]:
    candidates = [image_path]
    generated_paths: list[str] = []

    enable_crops = os.getenv('OCR_CROP_PASSES', 'true').lower() == 'true'
    enable_enhance = os.getenv('OCR_ENHANCE', 'false').lower() == 'true'
    upscale_factor = float(os.getenv('OCR_UPSCALE_FACTOR', '2.0'))
    if upscale_factor < 1.0:
        upscale_factor = 1.0

    try:
        from PIL import Image, ImageEnhance, ImageOps
    except ModuleNotFoundError:
        return candidates, generated_paths

    try:
        base = Image.open(image_path).convert('RGB')
    except Exception:
        return candidates, generated_paths

    def save_variant(image_obj) -> None:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
            image_obj.save(tmp.name, format='JPEG', quality=95)
            generated_paths.append(tmp.name)
            candidates.append(tmp.name)

    # Full-image upscale helps recover small text on bottle labels.
    if upscale_factor > 1.01:
        upscaled = base.resize(
            (int(base.width * upscale_factor), int(base.height * upscale_factor)),
            Image.Resampling.LANCZOS,
        )
        save_variant(upscaled)

    if enable_enhance:
        auto = ImageOps.autocontrast(base)
        sharp = ImageEnhance.Sharpness(auto).enhance(1.8)
        save_variant(sharp)

    if enable_crops:
        w, h = base.size
        crop_boxes = [
            (int(w * 0.20), int(h * 0.24), int(w * 0.80), int(h * 0.86)),  # central label area
            (int(w * 0.15), int(h * 0.18), int(w * 0.85), int(h * 0.92)),  # wider center pass
            (0, int(h * 0.40), w, h),  # bottom half for label body text
            (int(w * 0.25), int(h * 0.05), int(w * 0.75), int(h * 0.40)),  # neck text
        ]

        for box in crop_boxes:
            crop = base.crop(box)
            if crop.width < 30 or crop.height < 30:
                continue
            save_variant(crop)
            if upscale_factor > 1.01:
                crop_up = crop.resize(
                    (int(crop.width * upscale_factor), int(crop.height * upscale_factor)),
                    Image.Resampling.LANCZOS,
                )
                save_variant(crop_up)

    return candidates, generated_paths


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({'ok': False, 'error': 'Missing image path'}))
        return 2

    image_path = sys.argv[1]

    # Keep OCR worker conservative for runtime stability.
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    os.environ.setdefault('MKL_NUM_THREADS', '1')
    # Paddle CPU runtime in slim containers can hit oneDNN/PIR executor incompatibilities.
    os.environ.setdefault('FLAGS_use_mkldnn', '0')
    os.environ.setdefault('FLAGS_enable_pir_api', '0')
    os.environ.setdefault('FLAGS_enable_pir_in_executor', '0')

    try:
        import paddleocr
        from paddleocr import PaddleOCR

        use_gpu = os.getenv('OCR_USE_GPU', 'false').lower() == 'true'
        ocr_version = getattr(paddleocr, '__version__', '0.0.0')
        major_version = int(str(ocr_version).split('.')[0]) if str(ocr_version).split('.')[0].isdigit() else 0

        kwargs = {
            'lang': os.getenv('OCR_LANG', 'en'),
        }

        if major_version >= 3:
            # PaddleOCR 3.x uses text_det/text_rec argument names.
            kwargs['text_det_limit_side_len'] = int(os.getenv('OCR_DET_LIMIT_SIDE_LEN', '1536'))
            kwargs['text_det_box_thresh'] = float(os.getenv('OCR_DET_DB_BOX_THRESH', '0.30'))
            kwargs['text_det_thresh'] = float(os.getenv('OCR_DET_DB_THRESH', '0.25'))
            kwargs['text_rec_score_thresh'] = float(os.getenv('OCR_REC_SCORE_THRESH', '0.0'))
            kwargs['use_textline_orientation'] = True
            kwargs['enable_mkldnn'] = os.getenv('OCR_ENABLE_MKLDNN', 'false').lower() == 'true'
        else:
            # PaddleOCR 2.x uses legacy det_db/rec argument names.
            kwargs['show_log'] = os.getenv('OCR_SHOW_LOG', 'false').lower() == 'true'
            kwargs['det_limit_side_len'] = int(os.getenv('OCR_DET_LIMIT_SIDE_LEN', '1536'))
            kwargs['det_db_box_thresh'] = float(os.getenv('OCR_DET_DB_BOX_THRESH', '0.30'))
            kwargs['det_db_thresh'] = float(os.getenv('OCR_DET_DB_THRESH', '0.25'))
            kwargs['rec_score_thresh'] = float(os.getenv('OCR_REC_SCORE_THRESH', '0.0'))
            kwargs['use_angle_cls'] = True
            kwargs['use_gpu'] = use_gpu

        ocr = PaddleOCR(**kwargs)

        use_multi_pass = os.getenv('OCR_MULTI_PASS', 'false').lower() == 'true'
        min_line_chars = int(os.getenv('OCR_MIN_LINE_CHARS', '2'))
        candidate_paths, generated_paths = build_candidate_paths(image_path)

        all_lines: list[str] = []
        try:
            for candidate in candidate_paths:
                pass_modes = [True, False] if use_multi_pass else [True]
                for use_cls in pass_modes:
                    result = run_ocr_call(ocr, candidate, use_cls)
                    all_lines.extend(extract_text_lines(result))
        finally:
            for generated in generated_paths:
                if os.path.exists(generated):
                    os.remove(generated)

        lines = [line for line in dedupe_lines(all_lines) if len(line.strip()) >= min_line_chars]
        print(json.dumps({'ok': True, 'lines': lines}))
        return 0
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
