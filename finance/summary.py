from collections import defaultdict
from typing import Dict, Any
from .data_model import get_db
from bson.objectid import ObjectId
from datetime import datetime, timedelta


def _user_query(user_id):
    try:
        oid = ObjectId(user_id)
        return {"user_id": {"$in": [user_id, oid]}}
    except Exception:
        return {"user_id": user_id}


def total_income_vs_expense(user_id) -> Dict[str, float]:
    db = get_db()
    income_total = 0.0
    for doc in db.incomes.find(_user_query(user_id)):
        income_total += float(doc.get("amount", 0))

    expense_total = 0.0
    for doc in db.purchases.find(_user_query(user_id)):
        expense_total += float(doc.get("amount", 0))

    return {"income": income_total, "expense": expense_total, "balance": income_total - expense_total}


def expense_breakdown_by_subcategory(user_id) -> Dict[str, float]:
    db = get_db()
    breakdown: Dict[str, float] = defaultdict(float)
    for doc in db.purchases.find(_user_query(user_id)):
        subcat = doc.get("subcategory") or doc.get("category") or "Uncategorized"
        breakdown[subcat] += float(doc.get("amount", 0))
    return dict(breakdown)


def investments_vs_taxes(user_id) -> Dict[str, float]:
    db = get_db()
    investments = 0.0
    taxes = 0.0
    for doc in db.purchases.find(_user_query(user_id)):
        category = (doc.get("category") or "").lower()
        if category == "investment" or (doc.get("subcategory") or "").lower() == "investment":
            investments += float(doc.get("amount", 0))
        if category == "taxes" or (doc.get("subcategory") or "").lower() == "taxes":
            taxes += float(doc.get("amount", 0))
    return {"investments": investments, "taxes": taxes}


def monthly_cashflow(user_id) -> Dict[str, Any]:
    db = get_db()
    cashflow: Dict[str, Dict[str, float]] = {}

    for doc in db.incomes.find(_user_query(user_id)):
        month = datetime.strptime(doc.get("date", "1970-01-01"), "%Y-%m-%d").strftime("%Y-%m")
        cashflow.setdefault(month, {"income": 0.0, "expense": 0.0})["income"] += float(doc.get("amount", 0))

    for doc in db.purchases.find(_user_query(user_id)):
        month = datetime.strptime(doc.get("date", "1970-01-01"), "%Y-%m-%d").strftime("%Y-%m")
        cashflow.setdefault(month, {"income": 0.0, "expense": 0.0})["expense"] += float(doc.get("amount", 0))

    return cashflow


def spending_segments(user_id) -> Dict[str, float]:
    """Split expenses into Regular, Casual, Taxes, Investments.

    - Regular: groceries, bills, transport, medicine, toiletries, rent, stationery
    - Casual: everything else that isn't taxes/investments
    """
    db = get_db()
    regular_total = 0.0
    casual_total = 0.0
    taxes_total = 0.0
    investments_total = 0.0

    regular_keys = {
        "groceries", "bills", "transport", "medicine", "toiletries", "rent", "stationery",
        "food & dining"
    }

    for doc in db.purchases.find(_user_query(user_id)):
        amount = float(doc.get("amount", 0))
        category = (doc.get("category") or "").lower()
        subcategory = (doc.get("subcategory") or "").lower()

        if category == "taxes" or subcategory == "taxes":
            taxes_total += amount
        elif category == "investment" or subcategory == "investment":
            investments_total += amount
        elif category in regular_keys or subcategory in regular_keys:
            regular_total += amount
        else:
            casual_total += amount

    return {
        "regular": regular_total,
        "casual": casual_total,
        "taxes": taxes_total,
        "investments": investments_total,
    }


def last_30_days_segments(user_id) -> Dict[str, float]:
    db = get_db()
    since = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
    totals = {"regular": 0.0, "casual": 0.0, "taxes": 0.0, "investments": 0.0}
    regular_keys = {
        "groceries", "bills", "transport", "medicine", "toiletries", "rent", "stationery",
        "food & dining"
    }
    for doc in db.purchases.find(_user_query(user_id)):
        if (doc.get("date") or "") < since:
            continue
        amount = float(doc.get("amount", 0))
        category = (doc.get("category") or "").lower()
        subcategory = (doc.get("subcategory") or "").lower()
        if category == "taxes" or subcategory == "taxes":
            totals["taxes"] += amount
        elif category == "investment" or subcategory == "investment":
            totals["investments"] += amount
        elif category in regular_keys or subcategory in regular_keys:
            totals["regular"] += amount
        else:
            totals["casual"] += amount
    return totals


def last_30_days_breakdown(user_id) -> Dict[str, float]:
    db = get_db()
    since = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
    breakdown: Dict[str, float] = defaultdict(float)
    for doc in db.purchases.find(_user_query(user_id)):
        if (doc.get("date") or "") < since:
            continue
        subcat = doc.get("subcategory") or doc.get("category") or "Uncategorized"
        breakdown[subcat] += float(doc.get("amount", 0))
    return dict(breakdown)


def regular_spending_count(user_id, last_n_days: int | None = None) -> int:
    db = get_db()
    regular_keys = {
        "groceries", "bills", "transport", "medicine", "toiletries", "rent", "stationery",
        "food & dining"
    }
    query = _user_query(user_id)
    since = None
    if last_n_days is not None:
        since = (datetime.utcnow() - timedelta(days=last_n_days)).strftime("%Y-%m-%d")
    count = 0
    for doc in db.purchases.find(query):
        if since and (doc.get("date") or "") < since:
            continue
        category = (doc.get("category") or "").lower()
        subcategory = (doc.get("subcategory") or "").lower()
        if category in regular_keys or subcategory in regular_keys:
            count += 1
    return count


def top_3_categories(user_id, last_n_days: int = 30) -> list:
    """Return top 3 spending categories with amounts and friendly names."""
    breakdown = last_30_days_breakdown(user_id) if last_n_days == 30 else expense_breakdown_by_subcategory(user_id)
    
    # Friendly category names
    friendly_names = {
        "groceries": "🛒 Groceries & Food",
        "bills": "⚡ Bills & Utilities", 
        "transport": "🚗 Transport",
        "medicine": "💊 Medicine & Health",
        "rent": "🏠 Rent & Housing",
        "shopping": "🛍️ Shopping",
        "food & dining": "🍽️ Dining Out",
        "subscriptions": "📱 Subscriptions",
        "stationery": "📝 Stationery",
        "taxes": "💰 Taxes",
        "investment": "📈 Investments",
        "uncategorized": "❓ Other"
    }
    
    sorted_cats = sorted(breakdown.items(), key=lambda x: x[1], reverse=True)
    top_3 = []
    for i, (cat, amount) in enumerate(sorted_cats[:3]):
        friendly_name = friendly_names.get(cat.lower(), f"📋 {cat.title()}")
        top_3.append({
            "name": friendly_name,
            "amount": amount,
            "category": cat
        })
    return top_3


def cashflow_status(user_id) -> dict:
    """Return cashflow status with friendly message."""
    totals = total_income_vs_expense(user_id)
    balance = totals["balance"]
    
    if balance > 0:
        status = "positive"
        message = f"✅Great! You saved ₹{balance:,.0f} this month"
        color = "#10B981"
        icon = ""
    elif balance == 0:
        status = "neutral" 
        message = "You broke even this month"
        color = "#F59E0B"
        icon = "⚖️"
    else:
        status = "negative"
        message = f"You overspent by ₹{abs(balance):,.0f} this month"
        color = "#EF4444"
        icon = "⚠️"
    
    return {
        "status": status,
        "message": message,
        "color": color,
        "icon": icon,
        "balance": balance
    }


