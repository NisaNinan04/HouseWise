# Database Export & Import Guide

This guide explains how to export and import MongoDB data using JSON files, making it easy to share data across different environments.

## 📤 Exporting Data

To export all MongoDB collections to JSON files:

```bash
python3 export_db_data.py
```

This will:
- Connect to MongoDB (using `MONGO_URI` from `.env` or default `mongodb://localhost:27017/sem5`)
- Export all collections to the `db_export/` folder
- Create JSON files for each collection
- Generate a `metadata.json` file with export information

### Collections Exported

The following collections are exported:
- `users` - User accounts
- `purchases` - Expenses/orders (including Gmail imports)
- `incomes` - Income entries
- `incomes_recurring` - Recurring income definitions
- `bills` - Bill reminders
- `medical` - Medical reminders
- `savings_goals` - Savings goals
- `goal_contributions` - Contributions to savings goals
- `settings` - User settings
- `group_expenses` - Expenses within groups
- `groups` - Group definitions
- `user_sessions` - User session data

### Output

All JSON files are saved in the `db_export/` folder:
```
db_export/
├── users.json
├── purchases.json
├── incomes.json
├── incomes_recurring.json
├── bills.json
├── medical.json
├── savings_goals.json
├── goal_contributions.json
├── settings.json
├── group_expenses.json
├── groups.json
├── user_sessions.json
└── metadata.json
```

## 📥 Importing Data

To import data from JSON files into MongoDB:

```bash
python3 import_db_data.py
```

### Import Options

When you run the import script, you'll be prompted:

**"Clear existing data first? (yes/no)"**

- **`yes`** - Deletes ALL existing data, then imports from JSON files
  - Use this when you want a fresh start with the exported data
  - ⚠️ **WARNING**: This will DELETE all your current data!
  
- **`no`** - Keeps existing data, only imports NEW documents
  - Skips documents that already exist (by `_id`)
  - Use this to merge data or avoid duplicates

### What Gets Imported

The script will:
1. Read all JSON files from `db_export/` folder
2. Convert string IDs back to MongoDB ObjectIds
3. Handle nested ObjectIds (in arrays, nested objects)
4. Import documents into their respective collections
5. Show a summary of imported documents

## 🔄 Workflow for Sharing Data

### Step 1: Export Data (on source machine)
```bash
python3 export_db_data.py
```

### Step 2: Commit to Git
```bash
git add db_export/
git commit -m "Export database data"
git push
```

### Step 3: Pull and Import (on destination machine)
```bash
git pull
python3 import_db_data.py
# Answer 'yes' to clear existing data if you want the shared data
```

### Step 4: Verify in MongoDB Compass
1. Open MongoDB Compass
2. Connect to your MongoDB instance
3. Select your database (default: `sem5`)
4. Check collections to verify data was imported

## 📋 Requirements

Make sure you have:
- Python 3.x
- MongoDB running (local or Atlas)
- All dependencies from `requirements.txt` installed:
  ```bash
  pip install -r requirements.txt
  ```

### Key Dependencies
- `pymongo==4.6.1` - MongoDB driver
- `Flask-PyMongo==3.0.1` - Flask MongoDB integration
- `python-dotenv==1.0.0` - Environment variable management

## 🔧 Configuration

### MongoDB Connection

Set your MongoDB URI in a `.env` file:
```bash
MONGO_URI=mongodb://localhost:27017/sem5
```

Or for MongoDB Atlas:
```bash
MONGO_URI=mongodb+srv://username:password@cluster.mongodb.net/sem5
```

## ⚠️ Important Notes

1. **ObjectId Conversion**: The scripts automatically handle conversion between MongoDB ObjectIds and JSON strings
2. **Nested ObjectIds**: All ObjectId fields (user_id, goal_id, group_id, etc.) are properly converted
3. **Dates**: Datetime objects are converted to ISO format strings
4. **Duplicates**: The import script checks for existing documents by `_id` to avoid duplicates
5. **Data Integrity**: All relationships between collections (via ObjectIds) are preserved

## 🐛 Troubleshooting

### "Cannot connect to MongoDB"
- Ensure MongoDB is running: `mongod` or check MongoDB service
- Verify `MONGO_URI` in `.env` file
- For MongoDB Atlas: Check IP whitelist and credentials

### "Export directory 'db_export' not found"
- Run `export_db_data.py` first to create the directory
- Or pull from git if the directory exists in the repository

### "No documents were imported"
- Check if you answered 'yes' to clear existing data
- Verify JSON files exist in `db_export/` folder
- Check error messages in the console output
- Ensure MongoDB connection is working

### "Duplicate key error"
- This means documents with the same `_id` already exist
- Answer 'yes' to clear existing data if you want to replace them
- Or manually delete specific collections in MongoDB Compass

## 📊 Verifying Data

After import, verify in MongoDB Compass:
1. Check collection counts match expected numbers
2. Verify relationships (e.g., purchases linked to users via `user_id`)
3. Check that dates are properly formatted
4. Ensure nested data (arrays, objects) are intact

## 🔄 Updating Exported Data

To update the exported JSON files with latest data:
```bash
python3 export_db_data.py
git add db_export/
git commit -m "Update database export"
git push
```

This ensures the shared data is always up to date.

