# Data Persistence Guide

## ✅ How Data Persistence Works

### MongoDB Storage
- **Location**: Data is stored in MongoDB (persistent database)
- **Default**: `mongodb://localhost:27017/sem5`
- **Storage**: Data is written to disk, not in-memory
- **Persistence**: Data survives:
  - Database disconnections
  - Application restarts
  - Server reboots
  - Git push/pull operations

### Write Concern Configuration
All database operations use explicit write concern to ensure data persistence:

```python
WriteConcern(w=1, j=True, wtimeout=5000)
```

- **w=1**: Writes are acknowledged (data is written)
- **j=True**: Journal writes enabled (data committed to disk)
- **wtimeout=5000**: 5 second timeout for write operations

This ensures that when you insert/update data, it's immediately written to disk and won't be lost.

## 🔒 Data Protection

### Populate Scripts
The populate scripts (`populate_ml_data.py`, `restore_gmail_orders.py`) are **idempotent**:

1. **Check Before Adding**: Scripts check for existing data before adding new data
2. **No Duplicates**: Running scripts multiple times won't create duplicate data
3. **Preserve Existing**: Existing data is never deleted or overwritten
4. **Smart Addition**: Only adds data if user has less than expected minimum

### Example Protection
```python
# Check existing data first
existing_count = db.purchases.count_documents({"user_id": user_id})

# Only add if needed
if existing_count >= num_expenses:
    print("⚠️  User already has data, skipping...")
    return 0
```

## 📊 Data Collections

All data is stored in MongoDB collections:

- **`users`**: User accounts
- **`purchases`**: Expenses/orders (including Gmail imports)
- **`incomes`**: Income entries
- **`incomes_recurring`**: Recurring income definitions
- **`bills`**: Bill reminders
- **`medical`**: Medical reminders
- **`settings`**: User settings
- **`user_sessions`**: Session data

## 🚀 Verifying Data Persistence

Run the verification script:

```bash
python3 verify_data_persistence.py
```

This will:
- Check MongoDB connection
- Verify write concern settings
- Count all data in collections
- Check data integrity
- Confirm data is stored on disk

## ⚠️ Important Notes

1. **Git Operations**: Git push/pull only affects code files, NOT database data
2. **Database Location**: If using local MongoDB, data is in MongoDB's data directory
3. **Backup**: For production, set up regular MongoDB backups
4. **Environment Variables**: `MONGO_URI` can be set in `.env` file

## 🔄 Restoring Data

If you need to restore data:

1. **ML Data**: `python3 populate_ml_data.py` (checks existing data first)
2. **Gmail Orders**: `python3 restore_gmail_orders.py` (checks existing data first)
3. **Verify**: `python3 verify_data_persistence.py`

All scripts preserve existing data and only add what's missing.

## 📝 Best Practices

1. **Never delete collections** unless you want to start fresh
2. **Use populate scripts** to add sample data (they're safe to run multiple times)
3. **Check data counts** before running populate scripts
4. **Backup database** before major changes
5. **Use environment variables** for database connection in production

## 🛡️ Data Safety Features

- ✅ Write concern ensures disk writes
- ✅ Idempotent populate scripts
- ✅ Existing data checks before adding
- ✅ No accidental overwrites
- ✅ Data survives all operations

Your data is safe and persistent! 🎉

