#!/usr/bin/env python3
"""
Script to populate database with sample data for machine learning.
Creates 2 additional users and adds bills, expenses, medicines, and incomes for all users.
"""

import os
import sys
from datetime import datetime, timedelta, date, timezone
from pymongo import MongoClient, WriteConcern
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash
import random

# Connect to MongoDB with explicit write concern for data persistence
mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/sem5")
# w=1: Acknowledge write (ensures data is written to journal/disk)
# j=True: Journal write (ensures write is written to journal before acknowledgment)
# wtimeout=5000: 5 second timeout for write operations
write_concern = WriteConcern(w=1, j=True, wtimeout=5000)
client = MongoClient(mongo_uri)
db = client.get_database().with_options(write_concern=write_concern)

# Sample data for ML training
CATEGORIES = ["Groceries", "Shopping", "Food & Dining", "Transport", "Bills", "Entertainment", "Healthcare", "Education", "Travel", "Others"]
INCOME_SOURCES = ["Salary", "Freelance", "Investment", "Rent", "Business", "Other"]
BILL_NAMES = ["Electricity", "Water", "Internet", "Phone", "Rent", "Insurance", "Credit Card", "Loan EMI", "Gas", "Cable TV"]
MEDICAL_TYPES = ["Doctor Appointment", "Medicine Refill", "Lab Test", "Dental Checkup", "Eye Checkup", "Vaccination", "Health Screening"]

def create_users():
    """Create 2 new users for ML data"""
    users_data = [
        {
            "fullname": "Rajesh Kumar",
            "email": "rajesh.kumar@example.com",
            "password_hash": generate_password_hash("password123"),
            "created_at": datetime.now(timezone.utc) - timedelta(days=90)
        },
        {
            "fullname": "Priya Sharma",
            "email": "priya.sharma@example.com",
            "password_hash": generate_password_hash("password123"),
            "created_at": datetime.now(timezone.utc) - timedelta(days=60)
        }
    ]
    
    created_users = []
    for user_data in users_data:
        existing = db.users.find_one({"email": user_data["email"]})
        if existing:
            print(f"⚠️  User {user_data['email']} already exists, skipping...")
            created_users.append(existing)
        else:
            result = db.users.insert_one(user_data)
            print(f"✅ Created user: {user_data['fullname']} ({user_data['email']})")
            created_users.append(db.users.find_one({"_id": result.inserted_id}))
    
    return created_users

def get_all_users():
    """Get all users from database"""
    return list(db.users.find())

def add_expenses_for_user(user_id, num_expenses=30):
    """Add sample expenses for a user - spread across 12 weeks (84 days)"""
    # Check existing expenses count first
    existing_count = db.purchases.count_documents({
        "user_id": ObjectId(user_id) if isinstance(user_id, str) else user_id,
        "gmail_imported": {"$ne": True}  # Don't count Gmail orders
    })
    
    # Only add if user has less than expected minimum
    if existing_count >= num_expenses:
        print(f"⚠️  User {user_id} already has {existing_count} expenses, skipping addition")
        return 0
    
    # Calculate how many to add
    to_add = max(0, num_expenses - existing_count)
    if to_add == 0:
        return 0
    
    expenses = []
    # 12 weeks = 84 days
    start_date = datetime.now() - timedelta(days=84)
    
    for i in range(to_add):
        # Distribute evenly across 12 weeks
        expense_date = start_date + timedelta(days=random.randint(0, 83))
        category = random.choice(CATEGORIES)
        amount = round(random.uniform(50, 5000), 2)
        
        items_by_category = {
            "Groceries": ["Milk", "Bread", "Vegetables", "Fruits", "Rice", "Oil", "Spices"],
            "Shopping": ["Clothes", "Electronics", "Books", "Accessories", "Home Decor"],
            "Food & Dining": ["Restaurant", "Cafe", "Fast Food", "Delivery", "Snacks"],
            "Transport": ["Uber", "Petrol", "Metro", "Bus", "Parking"],
            "Bills": ["Electricity", "Water", "Internet", "Phone"],
            "Entertainment": ["Movie", "Concert", "Streaming", "Games"],
            "Healthcare": ["Medicine", "Doctor", "Lab Test", "Pharmacy"],
            "Education": ["Books", "Course", "Tuition", "Stationery"],
            "Travel": ["Flight", "Hotel", "Taxi", "Food"],
            "Others": ["Misc", "Gift", "Donation", "Repair"]
        }
        
        item = random.choice(items_by_category.get(category, ["Item"]))
        
        expense = {
            "user_id": ObjectId(user_id) if isinstance(user_id, str) else user_id,
            "item": item,
            "amount": amount,
            "date": expense_date.strftime('%Y-%m-%d'),
            "category": category,
            "description": f"{item} - {category}",
            "created_at": expense_date
        }
        expenses.append(expense)
    
    if expenses:
        db.purchases.insert_many(expenses)
        print(f"✅ Added {len(expenses)} expenses for user {user_id}")
    return len(expenses)

def add_incomes_for_user(user_id, num_incomes=12):
    """Add sample incomes for a user - spread across 12 weeks (84 days)"""
    # Check existing incomes count first
    existing_count = db.incomes.count_documents({
        "user_id": ObjectId(user_id) if isinstance(user_id, str) else user_id
    })
    
    # Check existing recurring incomes
    existing_recurring = db.incomes_recurring.count_documents({
        "user_id": ObjectId(user_id) if isinstance(user_id, str) else user_id
    })
    
    incomes = []
    # 12 weeks = 84 days
    start_date = datetime.now() - timedelta(days=84)
    
    # Add recurring salary only if it doesn't exist
    salary_amount = round(random.uniform(30000, 100000), 2)
    recurring_added = 0
    if existing_recurring == 0:
        db.incomes_recurring.insert_one({
            "user_id": ObjectId(user_id) if isinstance(user_id, str) else user_id,
            "source": "Salary",
            "amount": salary_amount,
            "frequency": "monthly",
            "day_of_month": random.randint(1, 5),
            "start_date": (start_date - timedelta(days=30)).strftime('%Y-%m-%d'),
            "active": True,
            "created_at": start_date - timedelta(days=30)
        })
        recurring_added = 1
    
    # Only add if user has less than expected minimum
    if existing_count >= num_incomes:
        print(f"⚠️  User {user_id} already has {existing_count} incomes, skipping addition")
        return existing_count + recurring_added
    
    # Calculate how many to add
    to_add = max(0, num_incomes - existing_count)
    
    # Add one-time incomes spread across 12 weeks
    for i in range(to_add):
        income_date = start_date + timedelta(days=random.randint(0, 83))
        source = random.choice(INCOME_SOURCES)
        amount = round(random.uniform(1000, 50000), 2) if source != "Salary" else salary_amount
        
        income = {
            "user_id": ObjectId(user_id) if isinstance(user_id, str) else user_id,
            "amount": amount,
            "date": income_date.strftime('%Y-%m-%d'),
            "source": source,
            "category": "Income",
            "created_at": income_date
        }
        incomes.append(income)
    
    if incomes:
        db.incomes.insert_many(incomes)
        print(f"✅ Added {len(incomes)} incomes + {recurring_added} recurring income for user {user_id}")
    return len(incomes) + recurring_added

def add_bills_for_user(user_id, user_email, num_bills=8):
    """Add sample bills for a user"""
    # Check existing bills count first
    existing_count = db.bills.count_documents({
        "user_id": ObjectId(user_id) if isinstance(user_id, str) else user_id
    })
    
    # Only add if user has less than expected minimum
    if existing_count >= num_bills:
        print(f"⚠️  User {user_id} already has {existing_count} bills, skipping addition")
        return 0
    
    # Calculate how many to add
    to_add = max(0, num_bills - existing_count)
    if to_add == 0:
        return 0
    
    bills = []
    start_date = datetime.now()
    
    for i in range(to_add):
        bill_name = random.choice(BILL_NAMES)
        amount = round(random.uniform(500, 5000), 2)
        due_date = start_date + timedelta(days=random.randint(1, 30))
        repeat_monthly = random.choice([True, False])
        
        bill = {
            "user_id": ObjectId(user_id) if isinstance(user_id, str) else user_id,
            "user_email": user_email,
            "name": bill_name,
            "amount": amount,
            "due_date": due_date.strftime('%Y-%m-%d'),
            "recipients": [user_email],
            "repeat_monthly": repeat_monthly,
            "broadcast": False,
            "created_at": datetime.now(timezone.utc) - timedelta(days=random.randint(1, 30))
        }
        bills.append(bill)
    
    if bills:
        db.bills.insert_many(bills)
        print(f"✅ Added {len(bills)} bills for user {user_id}")
    return len(bills)

def add_medical_for_user(user_id, user_email, num_medical=6):
    """Add sample medical reminders for a user"""
    # Check existing medical reminders count first
    existing_count = db.medical.count_documents({
        "user_id": ObjectId(user_id) if isinstance(user_id, str) else user_id
    })
    
    # Only add if user has less than expected minimum
    if existing_count >= num_medical:
        print(f"⚠️  User {user_id} already has {existing_count} medical reminders, skipping addition")
        return 0
    
    # Calculate how many to add
    to_add = max(0, num_medical - existing_count)
    if to_add == 0:
        return 0
    
    medicals = []
    start_date = datetime.now()
    
    for i in range(to_add):
        medical_type = random.choice(MEDICAL_TYPES)
        medical_date = start_date + timedelta(days=random.randint(1, 60))
        location = random.choice(["City Hospital", "Clinic", "Pharmacy", "Lab", "Dental Clinic"])
        
        medical = {
            "user_id": ObjectId(user_id) if isinstance(user_id, str) else user_id,
            "user_email": user_email,
            "title": medical_type,
            "date": medical_date.strftime('%Y-%m-%d'),
            "location": location,
            "recipients": [user_email],
            "broadcast": False,
            "created_at": datetime.now(timezone.utc) - timedelta(days=random.randint(1, 30))
        }
        medicals.append(medical)
    
    if medicals:
        db.medical.insert_many(medicals)
        print(f"✅ Added {len(medicals)} medical reminders for user {user_id}")
    return len(medicals)

def main():
    """Main function to populate all data"""
    print("🚀 Starting ML data population...")
    print("=" * 60)
    
    # Create new users
    print("\n📝 Creating new users...")
    new_users = create_users()
    
    # Get all users (including existing ones)
    print("\n👥 Fetching all users...")
    all_users = get_all_users()
    print(f"✅ Found {len(all_users)} total users")
    
    # Add data for each user
    print("\n📊 Adding data for all users...")
    print("=" * 60)
    
    total_expenses = 0
    total_incomes = 0
    total_bills = 0
    total_medical = 0
    
    for user in all_users:
        user_id = str(user['_id'])
        user_email = user['email']
        user_name = user['fullname']
        
        print(f"\n👤 Processing user: {user_name} ({user_email})")
        print("-" * 60)
        
        # Check if user is abc or s - add more data for them
        if user_email.lower() in ['a@gmail.com', 's@gmail.com']:
            # Add more data for abc and s users - ensure 12 weeks coverage
            # At least 3-5 expenses per week = 36-60 expenses over 12 weeks
            expenses_count = add_expenses_for_user(user_id, num_expenses=random.randint(50, 70))
            total_expenses += expenses_count
            
            # At least 1-2 incomes per week = 12-24 incomes over 12 weeks
            incomes_count = add_incomes_for_user(user_id, num_incomes=random.randint(18, 24))
            total_incomes += incomes_count
            
            bills_count = add_bills_for_user(user_id, user_email, num_bills=random.randint(12, 18))
            total_bills += bills_count
            
            medical_count = add_medical_for_user(user_id, user_email, num_medical=random.randint(10, 15))
            total_medical += medical_count
        else:
            # Regular amount for other users - ensure 12 weeks coverage
            # At least 2-4 expenses per week = 24-48 expenses over 12 weeks
            expenses_count = add_expenses_for_user(user_id, num_expenses=random.randint(35, 50))
            total_expenses += expenses_count
            
            # At least 1 income per week = 12-18 incomes over 12 weeks
            incomes_count = add_incomes_for_user(user_id, num_incomes=random.randint(14, 18))
            total_incomes += incomes_count
            
            bills_count = add_bills_for_user(user_id, user_email, num_bills=random.randint(8, 12))
            total_bills += bills_count
            
            medical_count = add_medical_for_user(user_id, user_email, num_medical=random.randint(7, 10))
            total_medical += medical_count
    
    # Summary
    print("\n" + "=" * 60)
    print("✅ Data population complete!")
    print("=" * 60)
    print(f"📊 Summary:")
    print(f"   - Users: {len(all_users)}")
    print(f"   - Total Expenses: {total_expenses}")
    print(f"   - Total Incomes: {total_incomes}")
    print(f"   - Total Bills: {total_bills}")
    print(f"   - Total Medical Reminders: {total_medical}")
    print("\n🎉 All data is now visible in the application!")
    print("=" * 60)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

