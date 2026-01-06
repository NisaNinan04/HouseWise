# ML Features Implementation

## Overview
This folder contains all machine learning features for HouseWise, including expense prediction using XGBoost and buying suggestions using statistical frequency analysis.

## Features Implemented

### 1. Expense Predictions (XGBoost)
- **Algorithm**: XGBoost Regression
- **Purpose**: Predict future expenses for the next 7 days
- **Features Used**:
  - Historical spending patterns (mean, std, max, min)
  - Time-based features (day of week, day of month, month, weekend)
  - Category patterns and frequency
  - Rolling averages (7-day, 30-day)
- **Route**: `/ml/predictions`
- **Output**: 
  - Daily predictions with amounts and categories
  - Smart suggestions (spending alerts, budget recommendations)

### 2. Buying Suggestions (Frequency Analysis)
- **Algorithm**: Statistical Frequency Analysis
- **Purpose**: Suggest items to buy based on purchase patterns
- **Analysis**:
  - Purchase frequency per item
  - Average days between purchases
  - Days since last purchase
  - Category-level reminders
- **Route**: `/ml/suggestions`
- **Output**:
  - Item suggestions with urgency levels
  - Category reminders
  - Estimated costs

## File Structure

```
ml_features/
├── models/
│   ├── expense_predictor.py      # XGBoost model for expense prediction
│   └── frequency_analyzer.py     # Statistical analysis for buying suggestions
├── utils/
│   └── data_loader.py            # MongoDB data loading utilities
├── templates/
│   └── ml_features/
│       ├── predictions.html      # Predictions page UI
│       └── suggestions.html      # Suggestions page UI
├── routes.py                     # Flask routes
├── ml_service.py                  # Main service interface
├── requirements.txt              # ML dependencies
└── README.md                     # Documentation
```

## How It Works

### Expense Prediction Flow
1. Load user expenses from MongoDB (last 84 days)
2. Prepare features (time-based, category-based, rolling averages)
3. Train XGBoost model on historical data
4. Predict expenses for next 7 days
5. Generate spending suggestions and alerts

### Buying Suggestions Flow
1. Load user expenses from MongoDB
2. Analyze purchase frequency per item
3. Calculate average days between purchases
4. Identify items likely to be purchased soon
5. Generate category-level reminders

## Usage

### Accessing ML Features
- **Predictions**: Navigate to "Predictions" in the sidebar or visit `/ml/predictions`
- **Suggestions**: Navigate to "Suggestions" in the sidebar or visit `/ml/suggestions`

### API Endpoints
- `GET /ml/api/predictions?days=7` - Get predictions as JSON
- `GET /ml/api/suggestions?top=10` - Get suggestions as JSON

## Requirements
- xgboost==2.0.3
- pandas==2.1.4
- numpy==1.26.2
- scikit-learn==1.3.2

## Notes
- ML features are optional - app works without them
- Requires at least 10 expense records for predictions
- All data is user-specific and isolated

