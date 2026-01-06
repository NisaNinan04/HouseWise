#!/usr/bin/env python3
"""
Script to add increased spending data in specific categories
to test how predictions change
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
from bson.objectid import ObjectId
import random

# Connect to MongoDB
mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/sem5")
client = MongoClient(mongo_uri)
db = client.get_database()

def add_increased_spending():
    """Add recent expenses with increased spending in specific categories"""
    print("🚀 Adding Increased Spending Data")
    print("=" * 60)
    
    # Get user
    user = db.users.find_one({'email': 'a@gmail.com'})
    if not user:
        print("❌ User 'a@gmail.com' not found")
        return
    
    user_id = user['_id']
    print(f"✅ Found user: {user.get('fullname', user.get('email'))}")
    print()
    
    # Categories to increase spending in
    increased_categories = {
        'Food & Dining': {
            'base_amount': 500,
            'increase_multiplier': 2.5,  # 2.5x increase
            'items': ['Restaurant', 'Cafe', 'Fast Food', 'Delivery', 'Dining Out']
        },
        'Entertainment': {
            'base_amount': 300,
            'increase_multiplier': 3.0,  # 3x increase
            'items': ['Movie', 'Concert', 'Streaming', 'Games', 'Events']
        },
        'Shopping': {
            'base_amount': 800,
            'increase_multiplier': 2.0,  # 2x increase
            'items': ['Clothes', 'Electronics', 'Accessories', 'Online Shopping']
        }
    }
    
    # Add expenses for last 2 weeks (recent data with increased spending)
    expenses = []
    start_date = datetime.now() - timedelta(days=14)
    
    for i in range(20):  # Add 20 expenses over 2 weeks
        expense_date = start_date + timedelta(days=random.randint(0, 13))
        
        # Choose a category to increase
        category = random.choice(list(increased_categories.keys()))
        cat_info = increased_categories[category]
        
        # Calculate increased amount
        base = cat_info['base_amount']
        multiplier = cat_info['increase_multiplier']
        amount = round(random.uniform(base * multiplier * 0.8, base * multiplier * 1.2), 2)
        
        item = random.choice(cat_info['items'])
        
        expenses.append({
            "user_id": user_id,
            "item": item,
            "amount": amount,
            "date": expense_date.strftime('%Y-%m-%d'),
            "category": category,
            "description": f"{item} - {category}",
            "created_at": expense_date.replace(tzinfo=timezone.utc)
        })
    
    # Insert expenses
    if expenses:
        db.purchases.insert_many(expenses)
        print(f"✅ Added {len(expenses)} expenses with increased spending")
        print()
        print("📊 Breakdown by category:")
        for cat, info in increased_categories.items():
            cat_expenses = [e for e in expenses if e['category'] == cat]
            if cat_expenses:
                total = sum(e['amount'] for e in cat_expenses)
                avg = total / len(cat_expenses)
                print(f"   {cat}: {len(cat_expenses)} expenses, Avg: ₹{avg:,.0f} (increased by {info['increase_multiplier']}x)")
        
        print()
        print("=" * 60)
        print("✅ Increased spending data added!")
        print("=" * 60)
        print("\n💡 Now check predictions to see how they've changed!")
        print("   The system should detect increased spending in these categories")
        print("   and provide suggestions to cut down.")

if __name__ == "__main__":
    try:
        add_increased_spending()
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

