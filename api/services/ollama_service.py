import json
import os
import re
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest


class OllamaService:
    def __init__(self, project_root: Path):
        self.project_root = project_root

    @staticmethod
    def extract_first_json_object(text: str) -> dict[str, Any] | None:
        if not text:
            return None
        text = text.strip()
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        start = text.find("{")
        while start != -1:
            depth = 0
            for index in range(start, len(text)):
                char = text[index]
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start : index + 1]
                        try:
                            parsed = json.loads(candidate)
                            if isinstance(parsed, dict):
                                return parsed
                        except json.JSONDecodeError:
                            break
            start = text.find("{", start + 1)
        return None

    @staticmethod
    def _resolve_path(project_root: Path, path_value: str) -> Path:
        raw = Path(path_value)
        if raw.is_absolute():
            return raw
        return project_root / raw

    def call_additional_verification(self, ocr_payload: dict[str, Any]) -> dict[str, Any]:
        ollama_enabled = os.getenv("OLLAMA_ENABLED", "true").lower() == "true"
        if not ollama_enabled:
            return {
                "enabled": False,
                "error": "OLLAMA_ENABLED is false",
                "raw": "",
                "parsed": None,
            }

        prompt_path = self._resolve_path(
            self.project_root,
            os.getenv("OLLAMA_PROMPT_PATH", "prompts/ollama_inference_prompt.txt"),
        )
        model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        timeout_seconds = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "60"))

        try:
            prompt_template = prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {
                "enabled": True,
                "error": f"Prompt file not found: {prompt_path}",
                "raw": "",
                "parsed": None,
                "model": model,
            }

        prompt = prompt_template.replace("{{OCR_RESPONSE_JSON}}", json.dumps(ocr_payload, ensure_ascii=True, indent=2))
        body = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
        }

        endpoint = f"{base_url.rstrip('/')}/api/generate"
        req = urlrequest.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlrequest.urlopen(req, timeout=timeout_seconds) as response:
                raw_response = response.read().decode("utf-8")
        except urlerror.URLError as exc:
            return {
                "enabled": True,
                "error": f"Ollama request failed: {exc}",
                "raw": "",
                "parsed": None,
                "model": model,
            }

        try:
            parsed_response = json.loads(raw_response)
        except json.JSONDecodeError:
            return {
                "enabled": True,
                "error": "Ollama returned invalid JSON response envelope",
                "raw": raw_response,
                "parsed": None,
                "model": model,
            }

        llm_text = parsed_response.get("response", "")
        llm_json = self.extract_first_json_object(llm_text)

        return {
            "enabled": True,
            "error": None if llm_json is not None else "Could not parse JSON from Ollama response",
            "raw": llm_text,
            "parsed": llm_json,
            "model": model,
        }


def normalize_text_key(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def looks_like_class_type(value: str) -> bool:
    lowered = value.lower()
    class_keywords = [
        "whiskey",
        "whisky",
        "bourbon",
        "vodka",
        "gin",
        "rum",
        "tequila",
        "brandy",
        "liqueur",
        "wine",
        "beer",
        "ale",
        "lager",
        "stout",
        "porter",
        "cider",
    ]
    return any(keyword in lowered for keyword in class_keywords)


def looks_like_producer(value: str) -> bool:
    lowered = value.lower()
    producer_keywords = [
        "distillery",
        "distiller",
        "bottled by",
        "produced by",
        "imported by",
        "company",
        "co.",
        "inc",
        "llc",
    ]
    return any(keyword in lowered for keyword in producer_keywords)


def looks_like_alcohol_content(value: str) -> bool:
    import re

    return bool(
        re.search(r"\\b\\d{1,3}(?:\\.\\d+)?\\s*%\\b", value, flags=re.IGNORECASE)
        or re.search(r"\\b\\d{2,3}\\s*proof\\b", value, flags=re.IGNORECASE)
    )


def looks_like_net_contents(value: str) -> bool:
    import re

    return bool(re.search(r"\\b\\d+(?:\\.\\d+)?\\s?(?:ml|l|cl|fl\\.?\\s?oz|oz)\\b", value, flags=re.IGNORECASE))


def clean_brand_name(value: str) -> str:
    cleaned = value.strip()
    cleaned = re.sub(r"\b(distiller|distillery|bottled by|produced by|imported by)\b.*$", "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip(" ,.-")


def reconcile_fields(rule_fields: dict[str, Any], ollama_result: dict[str, Any]) -> dict[str, Any]:
    merged = {
        "brandName": rule_fields.get("brandName"),
        "classType": rule_fields.get("classType"),
        "alcoholContent": rule_fields.get("alcoholContent"),
        "netContents": rule_fields.get("netContents"),
        "countryOfOrigin": rule_fields.get("countryOfOrigin"),
        "producer": rule_fields.get("producer"),
    }

    model_parsed = ollama_result.get("parsed") if isinstance(ollama_result, dict) else None
    if not isinstance(model_parsed, dict):
        merged["class/type"] = merged["classType"]
        return merged

    model_class = model_parsed.get("classType") or model_parsed.get("class/type")
    model_brand = model_parsed.get("brandName")
    model_alcohol = model_parsed.get("alcoholContent")
    model_net = model_parsed.get("netContents")
    model_country = model_parsed.get("countryOfOrigin")
    model_producer = model_parsed.get("producer")

    if isinstance(model_class, str) and model_class.strip() and looks_like_class_type(model_class):
        merged["classType"] = model_class.strip()

    if isinstance(model_brand, str) and model_brand.strip():
        brand = clean_brand_name(model_brand)
        same_as_class = normalize_text_key(brand) == normalize_text_key(merged.get("classType"))
        if brand and not same_as_class and not looks_like_class_type(brand):
            merged["brandName"] = brand

    if isinstance(model_producer, str) and model_producer.strip() and looks_like_producer(model_producer):
        merged["producer"] = model_producer.strip()

    if isinstance(model_alcohol, str) and model_alcohol.strip() and looks_like_alcohol_content(model_alcohol):
        merged["alcoholContent"] = model_alcohol.strip()

    if isinstance(model_net, str) and model_net.strip() and looks_like_net_contents(model_net):
        merged["netContents"] = model_net.strip()

    if isinstance(model_country, str) and model_country.strip():
        merged["countryOfOrigin"] = model_country.strip()

    merged["class/type"] = merged["classType"]
    return merged
