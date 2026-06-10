import re
from dataclasses import dataclass
from typing import Any

try:
    from rapidfuzz import fuzz
except ModuleNotFoundError:
    fuzz = None


STANDARD_GOVERNMENT_WARNING = (
    "GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON GENERAL, WOMEN SHOULD NOT DRINK "
    "ALCOHOLIC BEVERAGES DURING PREGNANCY BECAUSE OF THE RISK OF BIRTH DEFECTS. "
    "(2) CONSUMPTION OF ALCOHOLIC BEVERAGES IMPAIRS YOUR ABILITY TO DRIVE A CAR OR "
    "OPERATE MACHINERY, AND MAY CAUSE HEALTH PROBLEMS."
)

COUNTRY_NAMES = [
    'united states',
    'usa',
    'canada',
    'mexico',
    'scotland',
    'ireland',
    'japan',
    'france',
    'italy',
    'spain',
    'germany',
    'australia',
    'new zealand',
    'india',
    'china',
    'korea',
    'taiwan',
]

CLASS_TYPE_KEYWORDS = [
    'whiskey',
    'whisky',
    'bourbon',
    'scotch',
    'vodka',
    'gin',
    'rum',
    'tequila',
    'mezcal',
    'brandy',
    'liqueur',
    'wine',
    'beer',
    'ale',
    'lager',
    'stout',
    'porter',
    'cider',
]


@dataclass
class FieldCheck:
    field: str
    expected: str
    detected: str
    score: float
    status: str
    reason: str


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_for_match(text: str) -> str:
    cleaned = normalize_spaces(text).lower()
    cleaned = re.sub(r"[^a-z0-9%./()-]+", "", cleaned)
    return cleaned


def similarity_score(left: str, right: str) -> float:
    if not left and not right:
        return 100.0
    if fuzz is not None:
        return float(fuzz.ratio(left, right))

    # Fallback if rapidfuzz is unavailable at runtime.
    from difflib import SequenceMatcher

    return SequenceMatcher(None, left, right).ratio() * 100.0


def best_line_match(expected: str, lines: list[str]) -> tuple[str, float]:
    expected_norm = normalize_for_match(expected)
    best_line = ""
    best_score = 0.0

    for line in lines:
        score = similarity_score(expected_norm, normalize_for_match(line))
        if score > best_score:
            best_score = score
            best_line = line

    return best_line, best_score


def strict_warning_check(full_text: str, expected_warning: str) -> FieldCheck:
    normalized_text = normalize_spaces(full_text)
    normalized_expected = normalize_spaces(expected_warning)

    exact_present = normalized_expected in normalized_text
    all_caps = normalized_expected == normalized_expected.upper()

    if exact_present and all_caps:
        return FieldCheck(
            field="government_warning",
            expected=expected_warning,
            detected=expected_warning,
            score=100.0,
            status="pass",
            reason="Exact required warning text found in uppercase.",
        )

    return FieldCheck(
        field="government_warning",
        expected=expected_warning,
        detected="",
        score=0.0,
        status="fail",
        reason="Required warning text not found exactly as expected in uppercase.",
    )


def evaluate_fuzzy_field(field: str, expected: str, lines: list[str]) -> FieldCheck:
    detected, score = best_line_match(expected, lines)

    if score >= 88:
        status = "pass"
        reason = "Strong match"
    elif score >= 72:
        status = "review"
        reason = "Possible match; manual review recommended"
    else:
        status = "fail"
        reason = "No reliable match found"

    return FieldCheck(
        field=field,
        expected=expected,
        detected=detected,
        score=round(score, 2),
        status=status,
        reason=reason,
    )


def evaluate_normalized_exact(field: str, expected: str, lines: list[str]) -> FieldCheck:
    expected_norm = normalize_for_match(expected)
    detected, score = best_line_match(expected, lines)
    detected_norm = normalize_for_match(detected)

    is_exact = expected_norm == detected_norm and expected_norm != ""
    status = "pass" if is_exact else ("review" if score >= 80 else "fail")
    reason = "Exact normalized match" if is_exact else "Could not confirm exact value"

    return FieldCheck(
        field=field,
        expected=expected,
        detected=detected,
        score=round(score, 2),
        status=status,
        reason=reason,
    )


def summarize_status(checks: list[FieldCheck]) -> str:
    if any(check.status == "fail" for check in checks):
        return "fail"
    if any(check.status == "review" for check in checks):
        return "review"
    return "pass"


def _canonical_country(name: str) -> str:
    lowered = name.lower()
    if lowered == 'usa':
        return 'United States'
    if lowered == 'korea':
        return 'Korea'
    return ' '.join(part.capitalize() for part in lowered.split())


def _best_brand_name(lines: list[str]) -> str | None:
    class_tokens = {'whiskey', 'whisky', 'bourbon', 'vodka', 'gin', 'rum', 'tequila', 'brandy', 'wine', 'beer'}
    producer_tokens = {'distillery', 'distiller', 'bottled', 'produced', 'imported', 'company', 'inc', 'llc'}
    blocked_tokens = {
        'distilled',
        'spirits',
        'plant',
        'number',
        'proof',
        'government',
        'supervision',
        'family',
        'owned',
        'bottled-in-bond',
    }

    candidates = [
        normalize_spaces(line)
        for line in lines
        if len(re.sub(r'[^A-Za-z]', '', line)) >= 5
        and not re.search(r'\d', line)
        and len(line.split()) <= 4
        and not any(token in line.lower() for token in class_tokens)
        and not any(token in line.lower() for token in producer_tokens)
        and not any(token in line.lower() for token in blocked_tokens)
    ]
    if not candidates:
        return None

    grouped: dict[str, tuple[int, str]] = {}
    for candidate in candidates:
        key = normalize_for_match(candidate)
        if not key:
            continue
        count, sample = grouped.get(key, (0, candidate))
        grouped[key] = (count + 1, sample)

    if not grouped:
        return None

    best_key = max(grouped.keys(), key=lambda k: (grouped[k][0], len(k)))
    return grouped[best_key][1]


def _best_class_type(lines: list[str]) -> str | None:
    def score(line: str) -> int:
        lowered = line.lower()
        if not any(keyword in lowered for keyword in CLASS_TYPE_KEYWORDS):
            return -100

        penalty_phrases = [
            'must adhere',
            'distinct rules',
            'product must be',
            'to be labeled',
            'legally',
            'the proof is defined',
        ]
        penalty = sum(25 for phrase in penalty_phrases if phrase in lowered)

        bonus = 0
        if 'straight' in lowered:
            bonus += 15
        if 'bourbon' in lowered:
            bonus += 15
        if 'whiskey' in lowered or 'whisky' in lowered:
            bonus += 15

        word_count = len(line.split())
        if word_count <= 6:
            bonus += 10
        if word_count > 10:
            penalty += 10

        return bonus - penalty

    best_line = None
    best_score = -999
    for line in lines:
        current_score = score(line)
        if current_score > best_score:
            best_score = current_score
            best_line = line

    if best_line and best_score > 0:
        return normalize_spaces(best_line)
    return None


def _best_alcohol_content(lines: list[str]) -> str | None:
    patterns = [
        r'\b\d{1,2}(?:\.\d)?\s*%\s*(?:alc\.?\s*/?\s*vol\.?)?\b',
        r'\b\d{2,3}\s*proof\b',
        r'\b\d{1,2}(?:\.\d)?\s*%\s*alc\.?\s*/\s*vol\.?\b',
    ]
    for line in lines:
        for pattern in patterns:
            match = re.search(pattern, line, flags=re.IGNORECASE)
            if match:
                return normalize_spaces(match.group(0))
    return None


def _best_net_contents(lines: list[str]) -> str | None:
    pattern = r'\b\d+(?:\.\d+)?\s?(?:ml|mL|l|L|cl|cL|fl\.?\s?oz|oz)\b'
    for line in lines:
        match = re.search(pattern, line, flags=re.IGNORECASE)
        if match:
            return normalize_spaces(match.group(0))
    return None


def _best_country(lines: list[str]) -> str | None:
    joined = ' '.join(lines).lower()
    for country in COUNTRY_NAMES:
        if country in joined:
            return _canonical_country(country)

    for line in lines:
        match = re.search(r'(?:product of|made in|distilled in|imported from)\s+([a-zA-Z ]+)', line, flags=re.IGNORECASE)
        if match:
            return normalize_spaces(match.group(1)).title()
    return None


def _best_producer(lines: list[str]) -> str | None:
    producer_markers = [
        'distillery',
        'distiller',
        'bottled by',
        'produced by',
        'imported by',
        'company',
        'co.',
        'inc',
        'llc',
    ]
    blocked_phrases = [
        'must adhere',
        'distinct rules',
        'to be labeled',
        'product must be',
        'proof is defined',
        'placed in barrel',
        'aged in new charred oak',
    ]

    best_candidate = None
    best_score = -1
    for line in lines:
        lowered = line.lower()
        if any(phrase in lowered for phrase in blocked_phrases):
            continue
        if any(marker in lowered for marker in producer_markers):
            score = 0
            if 'distill' in lowered:
                score += 3
            if 'bottled by' in lowered or 'produced by' in lowered or 'imported by' in lowered:
                score += 2
            if len(line.split()) <= 8:
                score += 1
            if score > best_score:
                best_score = score
                best_candidate = normalize_spaces(line)

    return best_candidate


def extract_structured_fields(ocr_lines: list[str]) -> dict[str, Any]:
    cleaned_lines = [normalize_spaces(line) for line in ocr_lines if normalize_spaces(line)]

    result = {
        'brandName': _best_brand_name(cleaned_lines),
        'classType': _best_class_type(cleaned_lines),
        'alcoholContent': _best_alcohol_content(cleaned_lines),
        'netContents': _best_net_contents(cleaned_lines),
        'countryOfOrigin': _best_country(cleaned_lines),
        'producer': _best_producer(cleaned_lines),
    }

    # Alias for clients expecting class/type literal key.
    result['class/type'] = result['classType']
    return result


def verify_label(ocr_lines: list[str], application: dict[str, Any]) -> dict[str, Any]:
    checks: list[FieldCheck] = []

    full_text = "\n".join(ocr_lines)

    fuzzy_fields = [
        "brand_name",
        "class_type",
        "name_address",
        "country_of_origin",
    ]

    exact_fields = [
        "alcohol_content",
        "net_contents",
    ]

    for field in fuzzy_fields:
        expected = application.get(field)
        if expected:
            checks.append(evaluate_fuzzy_field(field, str(expected), ocr_lines))

    for field in exact_fields:
        expected = application.get(field)
        if expected:
            checks.append(evaluate_normalized_exact(field, str(expected), ocr_lines))

    expected_warning = application.get("government_warning") or STANDARD_GOVERNMENT_WARNING
    checks.append(strict_warning_check(full_text, str(expected_warning)))

    return {
        "overall_status": summarize_status(checks),
        "checks": [check.__dict__ for check in checks],
        "ocr_line_count": len(ocr_lines),
    }
