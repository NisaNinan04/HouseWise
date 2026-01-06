#!/usr/bin/env python3
"""
Export MongoDB data to JSON files for sharing via git
Run this script to export all collections to the 'db_export' folder
"""
import sys
import os
import json
from datetime import datetime
from bson import ObjectId
from bson.json_util import dumps, loads
from finance.data_model import get_db

def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

def export_collection(db, collection_name, output_dir):
    """Export a collection to JSON file"""
    try:
        collection = db[collection_name]
        count = collection.count_documents({})
        
        if count == 0:
            print(f"  ⚠️  {collection_name}: No documents to export")
            return 0
        
        # Get all documents
        documents = list(collection.find({}))
        
        # Convert ObjectId to string for JSON serialization
        def convert_objectids(obj):
            """Recursively convert ObjectIds to strings"""
            if isinstance(obj, ObjectId):
                return str(obj)
            elif isinstance(obj, datetime):
                return obj.isoformat()
            elif isinstance(obj, dict):
                return {k: convert_objectids(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_objectids(item) for item in obj]
            return obj
        
        # Convert all ObjectIds in documents
        documents = [convert_objectids(doc) for doc in documents]
        
        # Write to JSON file
        output_file = os.path.join(output_dir, f"{collection_name}.json")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(documents, f, indent=2, default=json_serial, ensure_ascii=False)
        
        print(f"  ✅ {collection_name}: {count} documents exported to {output_file}")
        return count
    except Exception as e:
        print(f"  ❌ {collection_name}: Error - {e}")
        return 0

def main():
    print("=" * 70)
    print("📤 EXPORTING MONGODB DATA TO JSON FILES")
    print("=" * 70)
    print()
    
    db = get_db()
    if db is None:
        print("❌ Cannot connect to MongoDB")
        sys.exit(1)
    
    # Create export directory
    export_dir = "db_export"
    os.makedirs(export_dir, exist_ok=True)
    
    # Collections to export - All collections used in the application
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
    
    total_docs = 0
    for collection_name in collections:
        count = export_collection(db, collection_name, export_dir)
        total_docs += count
    
    # Create metadata file
    metadata = {
        'export_date': datetime.now().isoformat(),
        'database_name': db.name,
        'collections_exported': collections,
        'total_documents': total_docs
    }
    
    metadata_file = os.path.join(export_dir, 'metadata.json')
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, default=json_serial)
    
    print()
    print("=" * 70)
    print(f"✅ Export complete! {total_docs} total documents exported")
    print(f"📁 Files saved to: {export_dir}/")
    print()
    print("📝 Next steps:")
    print("   1. Review the exported files in 'db_export/' folder")
    print("   2. Add 'db_export/' to git: git add db_export/")
    print("   3. Commit: git commit -m 'Export database data'")
    print("   4. Push: git push")
    print("=" * 70)

if __name__ == "__main__":
    main()

