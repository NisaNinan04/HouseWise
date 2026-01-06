"""
Data loader utility for ML features
Loads user data from MongoDB for training and prediction
"""

import os
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime, timedelta
import pandas as pd
import numpy as np


def get_db():
    """
    Get MongoDB database connection with explicit write concern for data persistence.
    Write concern ensures writes are acknowledged and committed to disk.
    """
    from pymongo import WriteConcern
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/sem5")
    # w=1: Acknowledge write (ensures data is written to journal/disk)
    # j=True: Journal write (ensures write is written to journal before acknowledgment)
    # wtimeout=5000: 5 second timeout for write operations
    write_concern = WriteConcern(w=1, j=True, wtimeout=5000)
    client = MongoClient(mongo_uri)
    db = client.get_database()
    # Set write concern on database
    return db.with_options(write_concern=write_concern)


def load_user_expenses(user_id, days_back=84):
    """Load user expenses from database"""
    db = get_db()
    user_id_obj = ObjectId(user_id) if isinstance(user_id, str) else user_id
    
    start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    
    expenses = list(db.purchases.find({
        "user_id": user_id_obj,
        "date": {"$gte": start_date}
    }).sort("date", 1))
    
    if not expenses:
        return pd.DataFrame()
    
    # Convert to DataFrame
    df = pd.DataFrame(expenses)
    
    # Ensure date is datetime and extract features
    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    
    # Extract time-based features
    df['day_of_week'] = df['date'].dt.dayofweek
    df['day_of_month'] = df['date'].dt.day
    df['month'] = df['date'].dt.month
    df['week_of_year'] = df['date'].dt.isocalendar().week
    
    return df


def load_user_incomes(user_id, days_back=84):
    """Load user incomes from database"""
    db = get_db()
    user_id_obj = ObjectId(user_id) if isinstance(user_id, str) else user_id
    
    start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    
    incomes = list(db.incomes.find({
        "user_id": user_id_obj,
        "date": {"$gte": start_date}
    }).sort("date", 1))
    
    if not incomes:
        return pd.DataFrame()
    
    df = pd.DataFrame(incomes)
    df['date'] = pd.to_datetime(df['date'])
    
    return df


def prepare_expense_features(df):
    """Prepare features for expense prediction"""
    if df.empty:
        return pd.DataFrame()
    
    # Ensure date is datetime
    df = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df['date']):
        df['date'] = pd.to_datetime(df['date'])
    
    # Sort by date
    df = df.sort_values('date')
    
    # Create time-based features if not present
    if 'day_of_week' not in df.columns:
        df['day_of_week'] = df['date'].dt.dayofweek
    if 'day_of_month' not in df.columns:
        df['day_of_month'] = df['date'].dt.day
    if 'month' not in df.columns:
        df['month'] = df['date'].dt.month
    if 'is_weekend' not in df.columns:
        df['is_weekend'] = df['day_of_week'].isin([5, 6]).astype(int)
    
    # Group by date and category for daily totals
    daily_expenses = df.groupby(['date', 'category']).agg({
        'amount': 'sum',
        'day_of_week': 'first',
        'day_of_month': 'first',
        'month': 'first',
        'is_weekend': 'first'
    }).reset_index()
    
    # Rolling averages
    daily_expenses = daily_expenses.copy()
    daily_expenses['amount_7d_avg'] = daily_expenses.groupby('category')['amount'].transform(
        lambda x: x.rolling(window=7, min_periods=1).mean()
    )
    daily_expenses['amount_30d_avg'] = daily_expenses.groupby('category')['amount'].transform(
        lambda x: x.rolling(window=30, min_periods=1).mean()
    )
    
    return daily_expenses

