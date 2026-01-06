#!/bin/bash
# Script to run the HouseWise application

cd "$(dirname "$0")"

# Activate virtual environment
source venv/bin/activate

# Run the app
echo "🚀 Starting HouseWise application..."
echo "📍 App will be available at: http://localhost:5002"
echo ""
python3 app.py

