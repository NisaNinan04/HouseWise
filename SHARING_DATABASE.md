# Sharing MongoDB Data with Team Members

There are two ways to share the database with other users:

## Option 1: MongoDB Atlas (Cloud - Recommended) 🌟

**Best for:** Team collaboration, always-on access, automatic backups

### Setup Steps:

1. **Create MongoDB Atlas Account**
   - Go to https://www.mongodb.com/cloud/atlas
   - Sign up for free (M0 cluster is free forever)

2. **Create a Cluster**
   - Choose a free M0 cluster
   - Select your region
   - Wait for cluster to be created (~5 minutes)

3. **Get Connection String**
   - Click "Connect" on your cluster
   - Choose "Connect your application"
   - Copy the connection string (looks like: `mongodb+srv://username:password@cluster.mongodb.net/dbname`)

4. **Update .env file**
   ```bash
   MONGO_URI=mongodb+srv://username:password@cluster.mongodb.net/housewise?retryWrites=true&w=majority
   ```

5. **Add Team Members**
   - In Atlas dashboard, go to "Database Access"
   - Add team members with read/write permissions
   - They can use the same connection string

**Benefits:**
- ✅ Everyone connects to the same database
- ✅ Automatic backups
- ✅ No need to export/import
- ✅ Real-time collaboration
- ✅ Free tier available

---

## Option 2: Export/Import via Git (For Local Development)

**Best for:** Sharing initial data, backups, local development

### Export Data (Run once):

```bash
python3 export_db_data.py
```

This creates a `db_export/` folder with JSON files for each collection.

### Commit to Git:

```bash
git add db_export/
git commit -m "Export database data for sharing"
git push
```

### Import Data (Other users):

```bash
# Step 1: Pull the code and JSON files
git pull

# Step 2: Import the JSON files into MongoDB
python import_db_data.py
```

**Important:** 
- The JSON files are just files until you import them
- After running `import_db_data.py`, the data will be in MongoDB
- You can then see it in **MongoDB Compass** or any MongoDB client
- The import script will ask if you want to clear existing data first
- If you say "no", it will skip duplicates (won't re-import existing documents)

### Update .gitignore:

The `db_export/` folder is **NOT** ignored by default, so it will be committed to git. If you want to ignore it:

1. Edit `.gitignore` and uncomment `# db_export/`
2. Or keep it committed to share data with team

---

## Which Option to Choose?

- **MongoDB Atlas**: Use for production or when you want everyone to work on the same live database
- **Export/Import**: Use for sharing initial seed data or backups

---

## Current Database Stats

Run this to see current data:
```bash
python3 -c "from finance.data_model import get_db; db = get_db(); print('Users:', db.users.count_documents({})); print('Purchases:', db.purchases.count_documents({}))"
```

