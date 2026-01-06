import json
import os
import re
from typing import Dict, Optional, Tuple


def load_categories_config(config_path: Optional[str] = None) -> Dict:
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), "categories.json")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def classify_transaction(description: str, amount: float, config: Optional[Dict] = None) -> Tuple[str, Optional[str]]:
    if not description:
        description = ""

    description_lower = description.lower()
    if config is None:
        config = load_categories_config()

    # 1) Explicit rules (regex or keyword includes)
    rules = config.get("rules", [])
    for rule in rules:
        keywords = rule.get("keywords", [])
        pattern = rule.get("pattern")
        if pattern and re.search(pattern, description_lower):
            return rule["category"], rule.get("subcategory")
        if any(kw.lower() in description_lower for kw in keywords):
            return rule["category"], rule.get("subcategory")

    # 2) Heuristics
    if amount >= 0 and config.get("income_keywords"):
        if any(kw.lower() in description_lower for kw in config["income_keywords"]):
            return "Income", "Salary"

    # 3) Defaults
    default_category = config.get("default_category", "Expense")
    default_subcategory = config.get("default_subcategory")
    return default_category, default_subcategory


