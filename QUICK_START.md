# Quick Start Guide for Team Members

## First Time Setup

### 1. Clone/Pull the Repository
```bash
git clone <repository-url>
# OR if you already have it:
git pull
```

### 2. Set Up Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Set Up MongoDB Connection
Create a `.env` file in the project root:
```bash
MONGO_URI=mongodb://localhost:27017/housewise
# OR for MongoDB Atlas:
# MONGO_URI=mongodb+srv://username:password@cluster.mongodb.net/housewise
```

### 5. Import Database Data
```bash
python3 import_db_data.py
```

When prompted:
- **"Clear existing data first? (yes/no)"**: 
  - Type `yes` if you want a fresh start (will delete all existing data)
  - Type `no` if you want to keep existing data and only add new ones (skips duplicates)

### 6. Verify in MongoDB Compass

1. Open **MongoDB Compass**
2. Connect to your MongoDB (localhost or Atlas)
3. Select the `housewise` database
4. You should see collections:
   - `users` (6 users)
   - `purchases` (2,211 expenses)
   - `incomes` (392 income entries)
   - `bills` (247 bills)
   - `medical` (214 medical reminders)
   - And more...

### 7. Run the Application
```bash
python3 app.py
```

The app will run on `http://localhost:5002`

---

## What Gets Imported?

The `db_export/` folder contains JSON files for:
- ✅ Users (6 users: abc, s, john, test, rajesh, priya)
- ✅ Purchases/Expenses (2,211 records)
- ✅ Incomes (392 records)
- ✅ Recurring Incomes (25 definitions)
- ✅ Bills (247 records)
- ✅ Medical Reminders (214 records)
- ✅ Savings Goals (1 goal)
- ✅ User Sessions (4 sessions)

**Total: ~3,100 documents**

---

## Troubleshooting

### "Cannot connect to MongoDB"
- Make sure MongoDB is running: `mongod` (or check MongoDB service)
- Check your `.env` file has correct `MONGO_URI`
- For MongoDB Atlas: Check your IP is whitelisted

### "Export directory 'db_export' not found"
- Make sure you pulled the latest code: `git pull`
- The `db_export/` folder should be in the project root

### "No documents imported"
- Check if data already exists (script skips duplicates)
- Try clearing first: Type `yes` when asked

### Data not showing in MongoDB Compass
- Make sure you imported: `python3 import_db_data.py`
- Refresh MongoDB Compass (click the refresh button)
- Check you're looking at the correct database (`housewise`)

---

## Updating Data

If someone adds new data and exports it:

```bash
# Pull latest code (including new JSON files)
git pull

# Re-import (will skip duplicates, add new ones)
python3 import_db_data.py
# Type "no" when asked to clear existing data
```

---

## Need Help?

Check `SHARING_DATABASE.md` for more details on:
- MongoDB Atlas setup (cloud database)
- Export/import process
- Data sharing options

