import os
from typing import Optional
from .data_model import get_db
from .classification import classify_transaction, load_categories_config


def migrate_assign_categories(user_id: Optional[str] = None, dry_run: bool = True):
    db = get_db()
    config = load_categories_config()

    def needs_classification(doc):
        return not doc.get("category") or not doc.get("subcategory")

    # Purchases (expenses)
    for doc in db.purchases.find({} if not user_id else {"user_id": user_id}):
        if needs_classification(doc):
            description = doc.get("item") or doc.get("description") or ""
            category, subcategory = classify_transaction(description, float(doc.get("amount", 0)), config)
            if dry_run:
                print(f"Would update purchase {doc.get('_id')} -> {category}/{subcategory}")
            else:
                db.purchases.update_one({"_id": doc["_id"]}, {"$set": {"category": category, "subcategory": subcategory}})

    # Incomes (optional classification)
    for doc in db.incomes.find({} if not user_id else {"user_id": user_id}):
        if needs_classification(doc):
            description = doc.get("source") or doc.get("description") or ""
            category, subcategory = classify_transaction(description, float(doc.get("amount", 0)), config)
            if dry_run:
                print(f"Would update income {doc.get('_id')} -> {category}/{subcategory}")
            else:
                db.incomes.update_one({"_id": doc["_id"]}, {"$set": {"category": category, "subcategory": subcategory}})


if __name__ == "__main__":
    dry = os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes")
    migrate_assign_categories(dry_run=dry)



