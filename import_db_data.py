#!/usr/bin/env python3
"""
Import MongoDB data from JSON files
Run this script to restore data from the 'db_export' folder
"""
import sys
import os
import json
from bson import ObjectId
from datetime import datetime
from finance.data_model import get_db

def parse_json_date(date_str):
    """Parse ISO date string back to datetime"""
    try:
        return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    except:
        return datetime.now()

def import_collection(db, collection_name, input_dir, clear_existing=False):
    """Import a collection from JSON file"""
    input_file = os.path.join(input_dir, f"{collection_name}.json")
    
    if not os.path.exists(input_file):
        print(f"  ⚠️  {collection_name}: File not found, skipping")
        return 0
    
    try:
        # Read JSON file
        with open(input_file, 'r', encoding='utf-8') as f:
            documents = json.load(f)
        
        if not documents:
            print(f"  ⚠️  {collection_name}: No documents in file")
            return 0
        
        collection = db[collection_name]
        
        # Clear existing data if requested
        if clear_existing:
            result = collection.delete_many({})
            print(f"  🗑️  {collection_name}: Cleared {result.deleted_count} existing documents")
        
        # Convert string IDs back to ObjectId
        imported_count = 0
        skipped_count = 0
        
        for doc in documents:
            try:
                # Convert _id back to ObjectId
                if '_id' in doc and isinstance(doc['_id'], str):
                    try:
                        doc['_id'] = ObjectId(doc['_id'])
                    except:
                        pass
                
                # Common ObjectId field names to convert
                objectid_fields = ['user_id', 'owner_id', 'goal_id', 'group_id', 'category_id', 
                                  'sender_id', 'member_id', 'contributed_by', 'paid_by']
                
                for field in objectid_fields:
                    if field in doc and isinstance(doc[field], str):
                        try:
                            if len(doc[field]) == 24:  # Valid ObjectId string length
                                doc[field] = ObjectId(doc[field])
                        except:
                            pass
                
                # Convert nested ObjectIds (e.g., in arrays like members, pending_invites)
                for key, value in doc.items():
                    if isinstance(value, list):
                        for i, item in enumerate(value):
                            if isinstance(item, dict):
                                # Convert _id in nested dicts
                                if '_id' in item and isinstance(item['_id'], str):
                                    try:
                                        item['_id'] = ObjectId(item['_id'])
                                    except:
                                        pass
                                # Convert other ObjectId fields in nested dicts
                                for field in objectid_fields:
                                    if field in item and isinstance(item[field], str):
                                        try:
                                            if len(item[field]) == 24:
                                                item[field] = ObjectId(item[field])
                                        except:
                                            pass
                            elif isinstance(item, str) and len(item) == 24:  # ObjectId string in array
                                try:
                                    doc[key][i] = ObjectId(item)
                                except:
                                    pass
                
                # Check if document already exists (by _id)
                # Only skip if we're NOT clearing existing data
                if not clear_existing and '_id' in doc:
                    existing = collection.find_one({'_id': doc['_id']})
                    if existing:
                        skipped_count += 1
                        continue
                
                # Insert document
                try:
                    collection.insert_one(doc)
                    imported_count += 1
                except Exception as insert_error:
                    # Check if it's a duplicate key error (even after clearing)
                    if "duplicate key" in str(insert_error).lower() or "E11000" in str(insert_error):
                        skipped_count += 1
                        if imported_count == 0 and skipped_count <= 3:
                            print(f"    ⚠️  Duplicate key error (document already exists): {insert_error}")
                    else:
                        print(f"    ❌ Insert error: {insert_error}")
                        skipped_count += 1
                    continue
                
            except Exception as e:
                print(f"    ⚠️  Error processing document: {e}")
                if imported_count == 0 and skipped_count <= 3:
                    import traceback
                    print(f"    Full error: {traceback.format_exc()}")
                skipped_count += 1
                continue
        
        if imported_count > 0:
            print(f"  ✅ {collection_name}: {imported_count} imported, {skipped_count} skipped")
        elif skipped_count > 0:
            print(f"  ⚠️  {collection_name}: {imported_count} imported, {skipped_count} skipped (all were duplicates)")
        else:
            print(f"  ❌ {collection_name}: {imported_count} imported, {skipped_count} skipped (check errors above)")
        
        return imported_count
        
    except Exception as e:
        print(f"  ❌ {collection_name}: Error - {e}")
        return 0

def main():
    print("=" * 70)
    print("📥 IMPORTING MONGODB DATA FROM JSON FILES")
    print("=" * 70)
    print()
    
    db = get_db()
    if db is None:
        print("❌ Cannot connect to MongoDB")
        sys.exit(1)
    
    # Check if export directory exists
    import_dir = "db_export"
    if not os.path.exists(import_dir):
        print(f"❌ Export directory '{import_dir}' not found!")
        print("   Please run 'python3 export_db_data.py' first or pull from git")
        sys.exit(1)
    
    # Check for metadata
    metadata_file = os.path.join(import_dir, 'metadata.json')
    if os.path.exists(metadata_file):
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)
        print(f"📅 Export date: {metadata.get('export_date', 'Unknown')}")
        print(f"📊 Total documents in export: {metadata.get('total_documents', 0)}")
        print()
    
    # Check current data counts
    print("📊 Current MongoDB data:")
    for collection_name in ['users', 'purchases', 'incomes']:
        count = db[collection_name].count_documents({})
        if count > 0:
            print(f"   {collection_name}: {count} documents")
    print()
    
    # Ask for confirmation
    print("⚠️  IMPORT OPTIONS:")
    print("   'yes' = Clear ALL existing data, then import from JSON files")
    print("   'no'  = Keep existing data, only import NEW documents (skip duplicates)")
    print()
    response = input("Clear existing data first? (yes/no): ").strip().lower()
    clear_existing = response == 'yes'
    
    if clear_existing:
        print("🗑️  Clearing existing data...")
        print("   ⚠️  WARNING: This will DELETE all existing data!")
    else:
        print("📝 Importing (will skip documents with existing _id)...")
        print("   💡 If you see '0 imported', your local data has same IDs as JSON files")
        print("   💡 To import the shared data, answer 'yes' to clear first")
    
    print()
    
    # Collections to import - All collections used in the application
    collections = [
        'users',
        'purchases',
        'incomes',
        'incomes_recurring',
        'bills',
        'medical',
        'savings_goals',
        'goal_contributions',  # Contributions to savings goals
        'settings',
        'group_expenses',      # Expenses within groups
        'groups',              # Group definitions
        'user_sessions'       # User session data
    ]
    
    total_imported = 0
    for collection_name in collections:
        count = import_collection(db, collection_name, import_dir, clear_existing)
        total_imported += count
    
    print()
    print("=" * 70)
    print(f"✅ Import complete! {total_imported} documents imported")
    print("=" * 70)
    print()
    
    # Verify import
    print("📊 Verification - Current MongoDB data:")
    for collection_name in ['users', 'purchases', 'incomes', 'bills', 'medical']:
        count = db[collection_name].count_documents({})
        if count > 0:
            print(f"   {collection_name}: {count} documents")
    
    print()
    if total_imported == 0:
        print("⚠️  WARNING: No documents were imported!")
        print("   Possible reasons:")
        print("   1. All documents already exist (duplicate _id)")
        print("   2. JSON files are empty or corrupted")
        print("   3. Import errors occurred (check messages above)")
        print()
        print("   💡 Try:")
        print("      - Check if you answered 'yes' to clear existing data")
        print("      - Verify JSON files exist in 'db_export/' folder")
        print("      - Check error messages above for details")
    else:
        print("✅ Data successfully imported! Check MongoDB Compass to verify.")
    print("=" * 70)

if __name__ == "__main__":
    main()

