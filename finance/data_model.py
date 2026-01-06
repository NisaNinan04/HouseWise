import os
from typing import Any, Dict, Optional
from datetime import datetime
from pymongo import MongoClient, WriteConcern
from bson.objectid import ObjectId


def get_mongo_client() -> MongoClient:
    """
    Get MongoDB client for data persistence.
    """
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/sem5")
    return MongoClient(mongo_uri)


def get_db(db_name: Optional[str] = None):
    """
    Get MongoDB database with explicit write concern for data persistence.
    Write concern w=1 ensures writes are acknowledged and committed to disk.
    """
    client = get_mongo_client()
    # w=1: Acknowledge write (ensures data is written to journal/disk)
    # j=True: Journal write (ensures write is written to journal before acknowledgment)
    # wtimeout=5000: 5 second timeout for write operations
    write_concern = WriteConcern(w=1, j=True, wtimeout=5000)
    
    if db_name:
        db = client[db_name]
    else:
        # If URI includes database, PyMongo selects it via get_default_database
        try:
            db = client.get_default_database()
        except Exception:
            # Fallback to 'sem5' if not provided in URI
            db = client["sem5"]
    
    # Set write concern on database
    db = db.with_options(write_concern=write_concern)
    return db


def ensure_indexes():
    db = get_db()
    db.users.create_index("email", unique=True)
    db.incomes.create_index([("user_id", 1), ("date", -1)])
    db.purchases.create_index([("user_id", 1), ("date", -1)])
    db.purchases.create_index([("category", 1), ("subcategory", 1)])


def normalize_user_id(user_id: Any) -> Any:
    try:
        return ObjectId(user_id) if not isinstance(user_id, ObjectId) else user_id
    except Exception:
        return user_id


def insert_transaction(
    user_id: Any,
    amount: float,
    date_str: str,
    category: str,
    subcategory: Optional[str] = None,
    description: Optional[str] = None,
    source: Optional[str] = None,
    is_income: bool = False,
) -> str:
    db = get_db()
    doc: Dict[str, Any] = {
        "user_id": normalize_user_id(user_id),
        "amount": float(amount),
        "date": date_str,
        "category": category,
        "subcategory": subcategory,
        "description": description,
        "created_at": datetime.utcnow(),
    }
    if is_income:
        if source:
            doc["source"] = source
        result = db.incomes.insert_one(doc)
    else:
        if source:
            doc["source"] = source
        result = db.purchases.insert_one(doc)
    return str(result.inserted_id)


def update_transaction_category(
    collection: str,
    transaction_id: str,
    category: str,
    subcategory: Optional[str],
):
    db = get_db()
    db[collection].update_one(
        {"_id": ObjectId(transaction_id)},
        {"$set": {"category": category, "subcategory": subcategory}},
    )


def iter_transactions(collection: str, user_id: Optional[Any] = None):
    db = get_db()
    query: Dict[str, Any] = {}
    if user_id is not None:
        query["user_id"] = normalize_user_id(user_id)
    for doc in db[collection].find(query):
        yield doc


