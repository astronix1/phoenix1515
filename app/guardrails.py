"""Guardrails module for security, privacy, and normalization.

Features:
1. customer_id Privacy Gate (prevents cross-customer data leakage).
2. Injection Sanitizer (detects jailbreaks, prompt injection, and adversarial attacks).
3. Unit Normalizer (normalizes currencies, storage, memory, weight, and ratings).
"""

import re
from typing import Any, Dict, Optional, Tuple


class GuardrailResult:
    def __init__(self, passed: bool, reason: str = "", metadata: Optional[Dict[str, Any]] = None):
        self.passed = passed
        self.reason = reason
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "metadata": self.metadata,
        }


class InjectionSanitizer:
    """Detects and mitigates prompt injections, jailbreaks, and system override attempts."""

    INJECTION_PATTERNS = [
        r"(?i)\bignore\s+(all\s+)?(previous|prior|above|your)\s+(instructions|prompts|rules|directives)",
        r"(?i)\bdisregard\s+(all\s+)?(previous|prior|above)\s+(instructions|directives)",
        r"(?i)\byou\s+are\s+now\s+(an?\s+)?(unrestricted|dan|jailbreak|evil|system|root)",
        r"(?i)\bmode:\s*dan\b",
        r"(?i)\bsystem\s*prompt\s*override\b",
        r"(?i)\b(reveal|show|print|leak|output)\s+(your\s+)?(system\s+prompt|initial\s+prompt|developer\s+message)",
        r"(?i)\bdrop\s+table\s+[a-z0-9_]+",
        r"(?i)\bselect\s+.*\s+from\s+(information_schema|sqlite_master|users|audit_traces)",
        r"(?i)\bunion\s+select\b",
        r"(?i)```\s*(system|admin|override)",
        r"(?i)<\|im_start\|>",
        r"(?i)\[INST\]\s*<<SYS>>",
    ]

    @classmethod
    def sanitize(cls, text: str) -> Tuple[str, GuardrailResult]:
        """Checks for injection signals and strips dangerous characters."""
        if not text or not text.strip():
            return "", GuardrailResult(passed=True)

        for pattern in cls.INJECTION_PATTERNS:
            match = re.search(pattern, text)
            if match:
                return text, GuardrailResult(
                    passed=False,
                    reason=f"Prompt injection or system override detected: '{match.group(0)}'",
                    metadata={"pattern": pattern, "matched_text": match.group(0)},
                )

        # Basic sanitization of null bytes and anomalous control sequences
        sanitized = text.replace("\x00", "").strip()
        return sanitized, GuardrailResult(passed=True)


class CustomerIdPrivacyGate:
    """Enforces access control for customer personal data and order records."""

    @classmethod
    def is_order_related_query(cls, text: str) -> bool:
        return bool(re.search(r"\b(orders?|bought|purchased?|purchases|what did .+ buy|track|tracking|purchase history|shopping history)\b|खरीदा|खरीदे|kharid[ae]", text, re.I))

    @classmethod
    def check_access(cls, user_query: str, current_customer_id: Optional[str]) -> GuardrailResult:
        if not cls.is_order_related_query(user_query):
            return GuardrailResult(True)
        ids = re.findall(r"\bC-?\d+\b", user_query, re.I)
        own = re.search(r"\b(my|mine|i|meine|maine|mera|mere)\b|मेर[ेाी]|मैंने", user_query, re.I)
        foreign = re.search(r"(?:['’]s\s+(?:past |recent )?(?:orders?|purchases?|history)|\b(?:for|of) (?!my\b|me\b)(?:customer |shopper )?[A-Za-z]+|what did (?!I\b)\w+ buy)", user_query, re.I)
        if not current_customer_id or any(i.lower() != current_customer_id.lower() for i in ids) or foreign or not (own or ids):
            return GuardrailResult(False, "I can only show the selected shopper their own orders.")
        return GuardrailResult(True)


class UnitNormalizer:
    """Normalizes unstructured unit references into canonical numerical filters and standard values."""

    # Currency exchange estimation for test consistency: 1 USD ~ 83 INR
    USD_TO_INR = 83.0

    @classmethod
    def normalize_query_and_extract_filters(cls, query: str) -> Tuple[str, Dict[str, Any]]:
        filters: Dict[str, Any] = {}
        query = re.sub(r"(?<=\d),(?=\d)", "", query)
        query = re.sub(r"(?:₹|rs\.?\s*)?(\d+)\s*(?:रुपये?\s*)?(?:से कम|ke neeche|se kam)", r"under \1", query, flags=re.I)
        normalized = query

        # 1. Price extraction: "under $50", "below 50000 inr", "under 50k", "< 1500"
        # Match "under/below/less than/<= $50" or "under 5000" or "under 50k"
        price_under_match = re.search(
            r"(?i)(?:under|below|less\s+than|up\s+to|budget(?:\s+of)?|max(?:imum)?|<=?)\s*([$₹€£]?)\s*([0-9]+(?:\.[0-9]+)?)\s*(k|thousand|inr|usd|rs\.?|rupees)?",
            query,
        )
        if price_under_match:
            symbol = price_under_match.group(1)
            num = float(price_under_match.group(2))
            unit = (price_under_match.group(3) or "").lower()

            if unit in ["k", "thousand"]:
                num *= 1000.0

            if symbol == "$" or "usd" in unit:
                num *= cls.USD_TO_INR

            filters["max_price"] = round(num, 2)

        # Match "above/greater than/> 1000"
        price_above_match = re.search(
            r"(?i)(?:above|greater\s+than|more\s+than|min(?:imum)?|>=?)\s*([$₹€£]?)\s*([0-9]+(?:\.[0-9]+)?)\s*(k|thousand|inr|usd|rs\.?|rupees)?",
            query,
        )
        if price_above_match:
            symbol = price_above_match.group(1)
            num = float(price_above_match.group(2))
            unit = (price_above_match.group(3) or "").lower()

            if unit in ["k", "thousand"]:
                num *= 1000.0

            if symbol == "$" or "usd" in unit:
                num *= cls.USD_TO_INR

            filters["min_price"] = round(num, 2)

        # 2. RAM extraction: "16gb ram", "8 gb ram", "32gb"
        ram_match = re.search(r"(?i)\b([0-9]+)\s*(?:gb|gigabytes?)\s*ram\b", query)
        if ram_match:
            filters["ram_gb"] = int(ram_match.group(1))

        # 3. Storage extraction: "512gb ssd", "1tb storage", "256gb"
        storage_text = query[:ram_match.start()] + query[ram_match.end():] if ram_match else query
        storage_match = re.search(r"(?i)\b([0-9]+)\s*(gb|tb)\b", storage_text)
        if storage_match:
            filters["storage_gb"] = int(storage_match[1]) * (1024 if storage_match[2].lower() == "tb" else 1)

        size = re.search(r"\bsize\s*([0-9]+(?:\.5)?|xs|s|m|l|xl|xxl)\b", query, re.I)
        if size:
            filters["size"] = size[1]
        colour = re.search(r"\b(blue|red|green|black|white|yellow|grey|brown|purple|pink|silver)\b", query, re.I)
        if colour:
            filters["colour"] = colour[1].lower()

        # 4. Rating extraction: "rating > 4", "4 star and above", "4+ stars"
        rating_match = re.search(r"(?i)\b([3-5](?:\.[0-9])?)\s*(?:\+|stars?|\s*rating\s*(?:and\s+above|or\s+more))\b", query)
        if rating_match:
            filters["min_rating"] = float(rating_match.group(1))

        # 5. In-Stock requirement
        if re.search(r"(?i)\b(in\s+stock|available\s+now|ready\s+to\s+ship)\b", query):
            filters["in_stock_only"] = True

        return normalized, filters
