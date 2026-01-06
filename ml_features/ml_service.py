"""
ML Service - Main interface for ML features
Provides expense prediction and buying suggestions
"""

import sys
import os

# Add current directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

try:
    from utils.data_loader import load_user_expenses, prepare_expense_features
    from models.expense_predictor import ExpensePredictor
    from models.frequency_analyzer import FrequencyAnalyzer
    import pandas as pd
except ImportError:
    # Fallback for relative imports
    from .utils.data_loader import load_user_expenses, prepare_expense_features
    from .models.expense_predictor import ExpensePredictor
    from .models.frequency_analyzer import FrequencyAnalyzer
    import pandas as pd


class MLService:
    def __init__(self):
        # Will be initialized per user
        self.expense_predictor = None
        self.frequency_analyzer = FrequencyAnalyzer()
    
    def get_expense_predictions(self, user_id, days_ahead=7, incremental=True):
        """Get expense predictions for user with model persistence and incremental learning"""
        try:
            # Initialize predictor with user_id for model persistence
            if not self.expense_predictor or self.expense_predictor.user_id != user_id:
                self.expense_predictor = ExpensePredictor(user_id=user_id)
            
            # Load data
            df = load_user_expenses(user_id, days_back=84)
            
            if df.empty:
                return {
                    'predictions': [],
                    'suggestions': [],
                    'error': 'Not enough data for prediction. Add more expenses first.'
                }
            
            # Prepare features - use the full expense data, not just daily grouped
            df_features = prepare_expense_features(df)
            
            if df_features.empty or len(df_features) < 10:
                return {
                    'predictions': [],
                    'suggestions': [],
                    'error': 'Not enough data for prediction. Need at least 10 expense records.'
                }
            
            # Train model (with incremental learning if enabled)
            trained = self.expense_predictor.train(df_features, incremental=incremental)
            
            if not trained:
                return {
                    'predictions': [],
                    'suggestions': [],
                    'error': 'Model training failed - need more data (at least 10 records)'
                }
            
            # Get predictions
            predictions = self.expense_predictor.predict(df_features, days_ahead=days_ahead)
            
            # If predictions are empty or all zero, try to generate fallback predictions
            if not predictions or all(p.get('predicted_amount', 0) == 0 for p in predictions):
                # Use simple average-based prediction as fallback
                daily_totals = df.groupby('date')['amount'].sum()
                avg_daily_total = float(daily_totals.mean()) if len(daily_totals) > 0 else 0
                
                if avg_daily_total > 0:
                    from datetime import timedelta
                    last_date = df['date'].max()
                    predictions = []
                    for day_offset in range(1, days_ahead + 1):
                        target_date = last_date + timedelta(days=day_offset)
                        # Use 80% of average for conservative prediction
                        pred_amount = avg_daily_total * 0.8
                        
                        # Get most common category
                        if 'category' in df.columns and len(df) > 0:
                            most_common_cat = df['category'].mode()[0] if len(df['category'].mode()) > 0 else 'Others'
                        else:
                            most_common_cat = 'Others'
                        
                        predictions.append({
                            'date': target_date.strftime('%Y-%m-%d'),
                            'day_name': target_date.strftime('%A'),
                            'predicted_amount': round(pred_amount, 2),
                            'category': most_common_cat,
                            'top_categories': {most_common_cat: pred_amount * 0.6},
                            'confidence': 'low',
                            'suggestion': None
                        })
            
            # Get suggestions
            suggestions = self.expense_predictor.get_suggestions(df_features, predictions) if predictions else []
            
            # Get model info
            model_info = {}
            if self.expense_predictor.model_manager:
                metadata = self.expense_predictor.model_manager.load_metadata()
                accuracy_stats = self.expense_predictor.model_manager.get_accuracy_stats()
                if metadata:
                    model_info = {
                        'version': metadata.get('version'),
                        'training_samples': metadata.get('training_samples'),
                        'saved_at': metadata.get('saved_at'),
                        'accuracy': accuracy_stats
                    }
            
            # Detect peaks and category overboard warnings
            peaks = []
            category_warnings = {}  # Track category-level warnings
            
            for pred in predictions:
                if pred.get('suggestion') and pred['suggestion'].get('is_peak'):
                    category = pred['suggestion'].get('peak_category', '')
                    pred_amount = pred['predicted_amount']
                    avg_amount = pred['suggestion'].get('avg_amount', 0)
                    
                    # Calculate category-specific average from historical data
                    if 'category' in df.columns:
                        category_data = df[df['category'] == category]
                        if len(category_data) > 0:
                            category_avg = float(category_data.groupby('date')['amount'].sum().mean())
                            category_max = float(category_data.groupby('date')['amount'].sum().max())
                        else:
                            category_avg = avg_amount
                            category_max = avg_amount * 1.5
                    else:
                        category_avg = avg_amount
                        category_max = avg_amount * 1.5
                    
                    # Create category warning if not exists or update if this is worse
                    if category not in category_warnings or pred_amount > category_warnings[category]['predicted_amount']:
                        category_warnings[category] = {
                            'category': category,
                            'predicted_amount': pred_amount,
                            'recommended_amount': category_avg,  # Should only be this much
                            'max_amount': category_max,
                            'increase_pct': ((pred_amount / category_avg - 1) * 100) if category_avg > 0 else 0,
                            'date': pred['date'],
                            'day_name': pred.get('day_name', ''),
                            'message': f'Your {category} spending is going overboard. It should only be ₹{category_avg:,.0f} but predicted ₹{pred_amount:,.0f}',
                            'suggestion': pred['suggestion']
                        }
                    
                    peaks.append({
                        'date': pred['date'],
                        'day_name': pred.get('day_name', ''),
                        'category': category,
                        'predicted_amount': pred_amount,
                        'avg_amount': avg_amount,
                        'category_avg': category_avg,
                        'recommended_amount': category_avg,
                        'increase_pct': ((pred_amount / category_avg - 1) * 100) if category_avg > 0 else 0,
                        'suggestion': pred['suggestion']
                    })
            
            return {
                'predictions': predictions,
                'suggestions': suggestions,
                'peaks': peaks,  # Peak spending days
                'category_warnings': list(category_warnings.values()),  # Category-level warnings
                'total_predicted': sum(p['predicted_amount'] for p in predictions) if predictions else 0,
                'avg_daily': float(df['amount'].mean()) if not df.empty else 0,
                'model_info': model_info
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                'predictions': [],
                'suggestions': [],
                'error': f'Error generating predictions: {str(e)}'
            }
    
    def track_prediction_accuracy(self, user_id, predictions, actual_expenses):
        """Track prediction accuracy by comparing predictions with actual expenses"""
        try:
            if not self.expense_predictor or self.expense_predictor.user_id != user_id:
                self.expense_predictor = ExpensePredictor(user_id=user_id)
            
            if self.expense_predictor.model_manager and predictions and actual_expenses:
                return self.expense_predictor.model_manager.save_prediction_accuracy(
                    predictions, actual_expenses
                )
        except Exception as e:
            print(f"Error tracking accuracy: {e}")
        return None
    
    def get_model_versions(self, user_id):
        """Get all model versions for a user"""
        try:
            predictor = ExpensePredictor(user_id=user_id)
            if predictor.model_manager:
                return predictor.model_manager.get_all_versions()
        except Exception as e:
            print(f"Error getting model versions: {e}")
        return []
    
    def get_accuracy_history(self, user_id):
        """Get accuracy history for a user"""
        try:
            predictor = ExpensePredictor(user_id=user_id)
            if predictor.model_manager:
                return predictor.model_manager.get_accuracy_history()
        except Exception as e:
            print(f"Error getting accuracy history: {e}")
        return []
    
    def get_buying_suggestions(self, user_id, top_n=10):
        """Get buying suggestions based on frequency analysis"""
        try:
            # Load data
            df = load_user_expenses(user_id, days_back=84)
            
            if df.empty:
                return {
                    'item_suggestions': [],
                    'category_suggestions': [],
                    'error': 'No purchase data available. Add more expenses to get suggestions.'
                }
            
            # Get item suggestions
            item_suggestions = self.frequency_analyzer.get_buying_suggestions(df, top_n=top_n)
            
            # Get category suggestions
            category_suggestions = self.frequency_analyzer.get_category_suggestions(df)
            
            return {
                'item_suggestions': item_suggestions,
                'category_suggestions': category_suggestions[:5] if category_suggestions else []  # Top 5 categories
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                'item_suggestions': [],
                'category_suggestions': [],
                'error': f'Error generating suggestions: {str(e)}'
            }

