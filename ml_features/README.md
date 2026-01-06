# ML Features

This folder contains all machine learning features for HouseWise.

## Structure

```
ml_features/
├── models/              # ML models
│   ├── expense_predictor.py    # XGBoost expense prediction
│   └── frequency_analyzer.py   # Statistical frequency analysis
├── utils/               # Utility functions
│   └── data_loader.py          # Data loading from MongoDB
├── templates/           # ML feature templates
│   └── ml_features/
│       ├── predictions.html    # Expense predictions page
│       └── suggestions.html    # Buying suggestions page
├── routes.py           # Flask routes for ML features
├── ml_service.py       # Main ML service interface
└── requirements.txt    # ML dependencies
```

## Features

### 1. Expense Predictions (XGBoost)
- Predicts future expenses for next 7 days
- Uses XGBoost regression model
- Provides spending suggestions and alerts
- Route: `/ml/predictions`

### 2. Buying Suggestions (Frequency Analysis)
- Analyzes purchase patterns
- Suggests items to buy based on frequency
- Category-level reminders
- Route: `/ml/suggestions`

## Installation

```bash
pip install -r ml_features/requirements.txt
```

## Usage

The ML features are automatically registered when the Flask app starts. Access them via:
- Predictions: `/ml/predictions`
- Suggestions: `/ml/suggestions`

## Dependencies

- xgboost==2.0.3
- pandas==2.1.4
- numpy==1.26.2
- scikit-learn==1.3.2

