# Database Structure & How It Works

## Connection Setup

The application connects to MongoDB using:
- **Default URI**: `mongodb://localhost:27017/sem5`
- **Configurable**: Set `MONGO_URI` environment variable to override
- **Database Name**: `sem5` (or from URI)

```python
# Connection is initialized in app.py
mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/sem5")
mongo.init_app(app)
```

## Collections Overview

### ✅ Unified Collections (Using `user_id` ObjectId)

#### 1. **`purchases`** - Expenses/Spending
- **user_id**: ObjectId (links to `users` collection)
- **Fields**: `amount`, `date`, `category`, `subcategory`, `item`, `description`
- **Usage**: All expenses tracked per user
- **Query Example**:
  ```python
  purchases = mongo.db.purchases.find({
      "user_id": user_id,
      "date": {"$regex": "^2025-01"}
  })
  ```

#### 2. **`incomes`** - Income Entries
- **user_id**: ObjectId (links to `users` collection)
- **Fields**: `amount`, `date`, `source`, `category`
- **Usage**: All income entries per user
- **Query Example**:
  ```python
  incomes = mongo.db.incomes.find({
      "user_id": ObjectId(user_id),
      "date": {"$regex": "^2025-01"}
  })
  ```

#### 3. **`incomes_recurring`** - Recurring Income Definitions
- **user_id**: ObjectId (links to `users` collection)
- **Fields**: `source`, `amount`, `frequency`, `start_date`, `end_date`, `day_of_month`, `active`
- **Usage**: Define fixed/recurring income (salary, rent, etc.)
- **Query Example**:
  ```python
  recurring = mongo.db.incomes_recurring.find({
      "user_id": ObjectId(user_id),
      "active": True
  })
  ```

### ⚠️ Non-Unified Collections (Using `user_email` String)

#### 4. **`bills`** - Bill Reminders
- **user_email**: String (NOT `user_id`)
- **Fields**: `name`, `amount`, `due_date`, `recipients`, `repeat_monthly`, `broadcast`
- **Issue**: Uses email instead of ObjectId for consistency
- **Query Example**:
  ```python
  bills = mongo.db.bills.find({
      'user_email': session.get('user_email')
  })
  ```

#### 5. **`medical`** - Medical Reminders
- **user_email**: String (NOT `user_id`)
- **Fields**: `title`, `date`, `location`, `recipients`, `broadcast`
- **Issue**: Uses email instead of ObjectId for consistency
- **Query Example**:
  ```python
  medical = mongo.db.medical.find({
      'user_email': session.get('user_email')
  })
  ```

### 6. **`users`** - User Accounts
- **Fields**: `_id` (ObjectId), `email`, `password_hash`, `fullname`, `created_at`
- **Index**: `email` (unique)

## How User Isolation Works

### For Unified Collections (`purchases`, `incomes`, `incomes_recurring`)

1. **User ID Normalization**:
   ```python
   def normalize_user_id(user_id):
       # Converts string to ObjectId if needed
       return ObjectId(user_id) if not isinstance(user_id, ObjectId) else user_id
   ```

2. **Query Pattern**:
   ```python
   user_id = session.get('user_id')  # String from session
   
   # Query with user_id filter
   expenses = mongo.db.purchases.find({
       "user_id": user_id,  # Works with string or ObjectId
       "date": {"$regex": "^2025-01"}
   })
   ```

3. **Flexible Query Helper** (`finance/summary.py`):
   ```python
   def _user_query(user_id):
       try:
           oid = ObjectId(user_id)
           return {"user_id": {"$in": [user_id, oid]}}  # Handles both
       except:
           return {"user_id": user_id}
   ```

### For Non-Unified Collections (`bills`, `medical`)

Currently uses `user_email` from session:
```python
user_email = session.get('user_email')
bills = mongo.db.bills.find({'user_email': user_email})
```

**⚠️ Inconsistency**: This breaks the unified data model pattern.

## Database Indexes (Performance)

Indexes are created in `finance/data_model.py` via `ensure_indexes()`:

```python
db.users.create_index("email", unique=True)
db.incomes.create_index([("user_id", 1), ("date", -1)])
db.purchases.create_index([("user_id", 1), ("date", -1)])
db.purchases.create_index([("category", 1), ("subcategory", 1)])
```

**Missing Indexes**:
- `bills` collection: No index on `user_email` or `due_date`
- `medical` collection: No index on `user_email` or `date`
- `incomes_recurring`: No index on `user_id`

## Data Flow Example

### Adding an Expense:
```python
# 1. Get user_id from session (string)
user_id = session.get('user_id')

# 2. Insert purchase
mongo.db.purchases.insert_one({
    "user_id": user_id,  # String gets normalized if needed
    "item": "Groceries",
    "amount": 1500.00,
    "date": "2025-01-15",
    "category": "Groceries",
    "created_at": datetime.utcnow()
})

# 3. Query user's expenses
user_expenses = mongo.db.purchases.find({
    "user_id": user_id  # Automatically filters by user
})
```

### Dashboard Query:
```python
# Fetch expenses for selected month
expenses = mongo.db.purchases.find({
    "user_id": user_id,
    "date": {"$regex": "^2025-01"}  # January 2025
})

# Fetch incomes for selected month
incomes = mongo.db.incomes.find({
    "user_id": ObjectId(user_id),  # Explicit ObjectId conversion
    "date": {"$regex": "^2025-01"}
})
```

## Multi-User Support

### ✅ How It Works:
1. **Session stores user_id**: When user logs in, `user_id` is stored in Flask session
2. **All queries filter by user_id**: Ensures data isolation
3. **Indexes optimize queries**: Compound indexes on `(user_id, date)` for fast lookups

### ⚠️ Current Issues:
1. **Inconsistent field names**: `bills` and `medical` use `user_email` instead of `user_id`
2. **No user_id validation**: Some queries might not properly filter by user
3. **Missing indexes**: `bills` and `medical` collections lack proper indexes

## Recommendations

1. **Migrate `bills` and `medical` to use `user_id`**:
   - Change `user_email` → `user_id` (ObjectId)
   - Update all queries to use `user_id` from session
   - Add migration script for existing data

2. **Add missing indexes**:
   ```python
   db.bills.create_index([("user_id", 1), ("due_date", 1)])
   db.medical.create_index([("user_id", 1), ("date", 1)])
   db.incomes_recurring.create_index([("user_id", 1), ("active", 1)])
   ```

3. **Create unified `reminders` collection** (optional):
   - Consolidate `bills` and `medical` into one `reminders` collection
   - Use `type` field to distinguish: `type: "bill"` or `type: "medical"`
   - All use `user_id` (ObjectId) for consistency

