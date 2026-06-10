import inspect
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


class OCRService:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.ocr_engine = None

    def get_ocr_engine(self):
        if self.ocr_engine is not None:
            return self.ocr_engine

        import paddleocr
        from paddleocr import PaddleOCR

        init_params = inspect.signature(PaddleOCR.__init__).parameters
        use_gpu = os.getenv("OCR_USE_GPU", "false").lower() == "true"
        ocr_version = getattr(paddleocr, "__version__", "0.0.0")
        major_version = int(str(ocr_version).split(".")[0]) if str(ocr_version).split(".")[0].isdigit() else 0
        ocr_kwargs = {
            "lang": os.getenv("OCR_LANG", "en"),
        }
        if "show_log" in init_params:
            ocr_kwargs["show_log"] = os.getenv("OCR_SHOW_LOG", "false").lower() == "true"

        if major_version >= 3:
            ocr_kwargs["device"] = "gpu" if use_gpu else "cpu"
            if "use_textline_orientation" in init_params:
                ocr_kwargs["use_textline_orientation"] = True
            ocr_kwargs["enable_mkldnn"] = os.getenv("OCR_ENABLE_MKLDNN", "false").lower() == "true"
        else:
            ocr_kwargs["use_angle_cls"] = True
            ocr_kwargs["use_gpu"] = use_gpu

        self.ocr_engine = PaddleOCR(**ocr_kwargs)
        return self.ocr_engine

    @staticmethod
    def extract_text_lines(result: object) -> list[str]:
        lines: list[str] = []

        if not isinstance(result, list):
            return lines

        for page in result:
            if isinstance(page, dict):
                for text in page.get("rec_texts", []) or []:
                    if text:
                        lines.append(str(text))
                continue

            if not isinstance(page, list):
                continue

            for item in page:
                if isinstance(item, dict):
                    text = item.get("text") or item.get("rec_text") or ""
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

    @staticmethod
    def run_ocr_call(ocr: Any, image_path: str, use_cls: bool) -> object:
        try:
            if use_cls:
                return ocr.ocr(image_path, cls=True)
            return ocr.ocr(image_path)
        except TypeError:
            return ocr.ocr(image_path)

    @staticmethod
    def dedupe_lines(lines: list[str]) -> list[str]:
        seen = set()
        unique = []
        for line in lines:
            key = " ".join(line.split()).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(line)
        return unique

    def build_ocr_candidate_paths(self, image_path: str) -> tuple[list[str], list[str]]:
        candidates = [image_path]
        generated_paths: list[str] = []

        enhance = os.getenv("OCR_ENHANCE", "false").lower() == "true"
        if not enhance:
            return candidates, generated_paths

        try:
            import cv2
        except ModuleNotFoundError:
            return candidates, generated_paths

        image = cv2.imread(image_path)
        if image is None:
            return candidates, generated_paths

        upscale_factor = float(os.getenv("OCR_UPSCALE_FACTOR", "2.0"))
        if upscale_factor < 1.0:
            upscale_factor = 1.0

        h, w = image.shape[:2]
        upscaled = cv2.resize(
            image,
            (int(w * upscale_factor), int(h * upscale_factor)),
            interpolation=cv2.INTER_CUBIC,
        )

        gray = cv2.cvtColor(upscaled, cv2.COLOR_BGR2GRAY)
        denoised = cv2.fastNlMeansDenoising(gray, None, 15, 7, 21)
        thresholded = cv2.adaptiveThreshold(
            denoised,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            11,
        )
        blurred = cv2.GaussianBlur(denoised, (0, 0), 1.2)
        sharpened = cv2.addWeighted(denoised, 1.8, blurred, -0.8, 0)

        variants = [upscaled, thresholded, sharpened]
        for variant in variants:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_file:
                cv2.imwrite(temp_file.name, variant)
                generated_paths.append(temp_file.name)
                candidates.append(temp_file.name)

        return candidates, generated_paths

    def ocr_lines_from_path_in_process(self, image_path: str) -> list[str]:
        ocr = self.get_ocr_engine()
        use_multi_pass = os.getenv("OCR_MULTI_PASS", "false").lower() == "true"
        candidate_paths, generated_paths = self.build_ocr_candidate_paths(image_path)

        all_lines: list[str] = []
        best_lines: list[str] = []
        best_char_count = -1

        try:
            for candidate in candidate_paths:
                pass_modes = [True, False] if use_multi_pass else [True]
                for use_cls in pass_modes:
                    result = self.run_ocr_call(ocr, candidate, use_cls)
                    lines = self.extract_text_lines(result)
                    if lines:
                        all_lines.extend(lines)

                    char_count = sum(len(line) for line in lines)
                    if char_count > best_char_count:
                        best_char_count = char_count
                        best_lines = lines
        finally:
            for path in generated_paths:
                if os.path.exists(path):
                    os.remove(path)

        if not all_lines:
            return self.dedupe_lines(best_lines)

        return self.dedupe_lines(all_lines)

    def ocr_lines_from_path(self, image_path: str) -> list[str]:
        isolate = os.getenv("OCR_ISOLATE_PROCESS", "true").lower() == "true"
        if not isolate:
            return self.ocr_lines_from_path_in_process(image_path)

        worker_path = self.project_root / "ocr_worker.py"
        timeout_seconds = int(os.getenv("OCR_WORKER_TIMEOUT_SECONDS", "60"))

        command = [sys.executable, str(worker_path), image_path]
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds)
        if result.returncode != 0:
            stdout = (result.stdout or "").strip()
            stderr = (result.stderr or "").strip()
            worker_error = None
            if stdout:
                try:
                    parsed = json.loads(stdout)
                    if isinstance(parsed, dict):
                        worker_error = parsed.get("error")
                except json.JSONDecodeError:
                    worker_error = stdout

            details = worker_error or stderr or "No stderr output."
            raise RuntimeError(
                f"OCR worker crashed (exit {result.returncode}). {details}"
            )

        payload = json.loads(result.stdout or "{}")
        if not payload.get("ok"):
            raise RuntimeError(payload.get("error", "OCR worker failed"))
        return payload.get("lines", [])
