import json
import os
import tempfile

from flask import Blueprint, jsonify, request
import pg8000.dbapi as pgdb

from label_verification import STANDARD_GOVERNMENT_WARNING, extract_structured_fields, verify_label
from api.config import Settings
from api.services.ocr_service import OCRService
from api.services.ollama_service import OllamaService, reconcile_fields


def create_api_blueprint(settings: Settings) -> Blueprint:
    bp = Blueprint("api", __name__)
    ocr_service = OCRService(settings.project_root)
    ollama_service = OllamaService(settings.project_root)

    def load_application_payload(raw: str | None) -> dict:
        if not raw:
            return {}
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("application must be a JSON object")
        return parsed

    def to_canonical_fields(fields: dict) -> dict:
        return {
            "brandName": fields.get("brandName"),
            "classType": fields.get("classType") or fields.get("class/type"),
            "alcoholContent": fields.get("alcoholContent"),
            "netContents": fields.get("netContents"),
            "countryOfOrigin": fields.get("countryOfOrigin"),
            "producer": fields.get("producer"),
        }

    @bp.get("/health")
    def health() -> tuple:
        return jsonify({"status": "ok"}), 200

    @bp.post("/ocr")
    def run_ocr() -> tuple:
        if "file" not in request.files:
            return jsonify({"error": "Missing file field in multipart form data"}), 400

        uploaded_file = request.files["file"]
        if uploaded_file.filename == "":
            return jsonify({"error": "Empty filename"}), 400

        suffix = os.path.splitext(uploaded_file.filename)[1] or ".png"
        temp_path = None

        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                uploaded_file.save(temp_file.name)
                temp_path = temp_file.name

            lines = ocr_service.ocr_lines_from_path(temp_path)
            fields = extract_structured_fields(lines)
            return jsonify({"line_count": len(lines), "lines": lines, "fields": fields}), 200
        except ModuleNotFoundError:
            return jsonify({"error": "PaddleOCR is not installed. Use requirements-ocr.txt with Python 3.10-3.12."}), 500
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    @bp.get("/requirements")
    def requirements() -> tuple:
        required_fields = [
            "brand_name",
            "class_type",
            "alcohol_content",
            "net_contents",
            "name_address",
            "country_of_origin",
            "government_warning",
        ]
        return jsonify({"required_fields": required_fields, "standard_government_warning": STANDARD_GOVERNMENT_WARNING}), 200

    @bp.post("/verify")
    def verify_single() -> tuple:
        if "file" not in request.files:
            return jsonify({"error": "Missing file field in multipart form data"}), 400

        uploaded_file = request.files["file"]
        if uploaded_file.filename == "":
            return jsonify({"error": "Empty filename"}), 400

        temp_path = None
        suffix = os.path.splitext(uploaded_file.filename)[1] or ".png"

        try:
            application = load_application_payload(request.form.get("application"))

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                uploaded_file.save(temp_file.name)
                temp_path = temp_file.name

            ocr_lines = ocr_service.ocr_lines_from_path(temp_path)
            verification = verify_label(ocr_lines, application)
            verification["fields"] = extract_structured_fields(ocr_lines)
            verification["filename"] = uploaded_file.filename
            verification["processing_target_seconds"] = 5
            return jsonify(verification), 200
        except json.JSONDecodeError:
            return jsonify({"error": "application must be valid JSON"}), 400
        except ModuleNotFoundError:
            return jsonify({"error": "PaddleOCR is not installed. Use requirements-ocr.txt with Python 3.10-3.12."}), 500
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    @bp.post("/verify/ollama")
    def verify_with_ollama() -> tuple:
        if "file" not in request.files:
            return jsonify({"error": "Missing file field in multipart form data"}), 400

        uploaded_file = request.files["file"]
        if uploaded_file.filename == "":
            return jsonify({"error": "Empty filename"}), 400

        temp_path = None
        suffix = os.path.splitext(uploaded_file.filename)[1] or ".png"

        try:
            application = load_application_payload(request.form.get("application"))

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                uploaded_file.save(temp_file.name)
                temp_path = temp_file.name

            ocr_lines = ocr_service.ocr_lines_from_path(temp_path)
            fields = extract_structured_fields(ocr_lines)
            rule_verification = verify_label(ocr_lines, application)

            ocr_payload = {
                "fields": fields,
                "lines": ocr_lines,
                "checks": rule_verification.get("checks", []),
            }
            ollama_result = ollama_service.call_additional_verification(ocr_payload)
            final_fields = reconcile_fields(fields, ollama_result)

            return jsonify(
                {
                    "filename": uploaded_file.filename,
                    "line_count": len(ocr_lines),
                    "lines": ocr_lines,
                    "fields": fields,
                    "finalFields": final_fields,
                    "canonicalFields": to_canonical_fields(final_fields),
                    "ruleVerification": rule_verification,
                    "ollamaVerification": ollama_result,
                }
            ), 200
        except json.JSONDecodeError:
            return jsonify({"error": "application must be valid JSON"}), 400
        except ModuleNotFoundError:
            return jsonify({"error": "PaddleOCR is not installed. Use requirements-ocr.txt with Python 3.10-3.12."}), 500
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    @bp.post("/verify/ollama/canonical")
    def verify_with_ollama_canonical() -> tuple:
        if "file" not in request.files:
            return jsonify({"error": "Missing file field in multipart form data"}), 400

        uploaded_file = request.files["file"]
        if uploaded_file.filename == "":
            return jsonify({"error": "Empty filename"}), 400

        temp_path = None
        suffix = os.path.splitext(uploaded_file.filename)[1] or ".png"

        try:
            application = load_application_payload(request.form.get("application"))

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                uploaded_file.save(temp_file.name)
                temp_path = temp_file.name

            ocr_lines = ocr_service.ocr_lines_from_path(temp_path)
            fields = extract_structured_fields(ocr_lines)
            rule_verification = verify_label(ocr_lines, application)

            ocr_payload = {
                "fields": fields,
                "lines": ocr_lines,
                "checks": rule_verification.get("checks", []),
            }
            ollama_result = ollama_service.call_additional_verification(ocr_payload)
            final_fields = reconcile_fields(fields, ollama_result)

            return jsonify(to_canonical_fields(final_fields)), 200
        except json.JSONDecodeError:
            return jsonify({"error": "application must be valid JSON"}), 400
        except ModuleNotFoundError:
            return jsonify({"error": "PaddleOCR is not installed. Use requirements-ocr.txt with Python 3.10-3.12."}), 500
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    @bp.post("/verify/batch")
    def verify_batch() -> tuple:
        files = request.files.getlist("files")
        if not files:
            return jsonify({"error": "Missing files[] in multipart form data"}), 400

        if len(files) > 300:
            return jsonify({"error": "Batch exceeds 300 files"}), 400

        try:
            raw_applications = request.form.get("applications", "[]")
            applications = json.loads(raw_applications)
            if not isinstance(applications, list):
                return jsonify({"error": "applications must be a JSON list"}), 400
        except json.JSONDecodeError:
            return jsonify({"error": "applications must be valid JSON"}), 400

        by_filename = {}
        for item in applications:
            if isinstance(item, dict) and item.get("filename"):
                by_filename[item["filename"]] = item

        results = []
        temp_paths: list[str] = []

        try:
            for index, file_item in enumerate(files):
                if file_item.filename == "":
                    continue

                suffix = os.path.splitext(file_item.filename)[1] or ".png"
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                    file_item.save(temp_file.name)
                    temp_paths.append(temp_file.name)

                    ocr_lines = ocr_service.ocr_lines_from_path(temp_file.name)

                app_payload = by_filename.get(file_item.filename)
                if app_payload is None and index < len(applications) and isinstance(applications[index], dict):
                    app_payload = applications[index]
                app_payload = app_payload or {}

                verification = verify_label(ocr_lines, app_payload)
                verification["fields"] = extract_structured_fields(ocr_lines)
                verification["filename"] = file_item.filename
                results.append(verification)

            summary = {
                "total": len(results),
                "pass": len([r for r in results if r["overall_status"] == "pass"]),
                "review": len([r for r in results if r["overall_status"] == "review"]),
                "fail": len([r for r in results if r["overall_status"] == "fail"]),
            }
            return jsonify({"summary": summary, "results": results}), 200
        except ModuleNotFoundError:
            return jsonify({"error": "PaddleOCR is not installed. Use requirements-ocr.txt with Python 3.10-3.12."}), 500
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            for path in temp_paths:
                if os.path.exists(path):
                    os.remove(path)

    return bp
