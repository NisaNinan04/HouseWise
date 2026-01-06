"""
ML Features Routes
Routes for expense prediction and buying suggestions
"""

from flask import Blueprint, render_template, request, jsonify, session, flash, redirect, url_for
from functools import wraps
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ml_features.ml_service import MLService

# Get the directory where this file is located
ml_features_dir = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(ml_features_dir, 'templates')
ml_bp = Blueprint('ml', __name__, url_prefix='/ml', template_folder=template_dir)
ml_service = MLService()


def login_required_ml(f):
    """Decorator to check if user is logged in"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Please login first'}), 401
        return f(*args, **kwargs)
    return decorated_function


@ml_bp.route('/predictions')
@login_required_ml
def predictions():
    """Expense predictions page"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'User not logged in'}), 401
    
    days_ahead = request.args.get('days', 7, type=int)
    
    try:
        incremental = request.args.get('incremental', 'true').lower() == 'true'
        result = ml_service.get_expense_predictions(user_id, days_ahead=days_ahead, incremental=incremental)
        # Ensure all keys are present
        result.setdefault('predictions', [])
        result.setdefault('suggestions', [])
        
        # Recalculate total_predicted from actual predictions if it's 0 or missing
        if result.get('total_predicted', 0) == 0 and result.get('predictions'):
            result['total_predicted'] = sum(p.get('predicted_amount', 0) for p in result['predictions'])
        
        result.setdefault('total_predicted', 0)
        result.setdefault('avg_daily', 0)
        result.setdefault('model_info', {})
        
        # Get actual expenses for past predictions to show savings
        from ml_features.utils.data_loader import get_db
        from bson.objectid import ObjectId
        from datetime import datetime, timedelta
        
        db = get_db()
        user_id_obj = ObjectId(user_id) if isinstance(user_id, str) else user_id
        
        # Get actual expenses for dates that were previously predicted (for all dates, not just past)
        actual_vs_predicted = {}
        today = datetime.now().date()
        
        for pred in result.get('predictions', []):
            pred_date = datetime.strptime(pred['date'], '%Y-%m-%d').date()
            # Get actual expenses for this date (past, present, or future - for real-time tracking)
            actual_expenses = list(db.purchases.find({
                "user_id": user_id_obj,
                "date": pred['date']
            }))
            actual_total = sum(e.get('amount', 0) for e in actual_expenses)
            predicted_amount = pred.get('predicted_amount', 0)
            
            # Always include in comparison for real-time updates
            savings = predicted_amount - actual_total
            actual_vs_predicted[pred['date']] = {
                'predicted': predicted_amount,
                'actual': actual_total,
                'savings': savings,
                'status': 'saved' if savings > 0 and actual_total > 0 else ('overspent' if actual_total > predicted_amount else 'pending')
            }
        
        result['actual_vs_predicted'] = actual_vs_predicted
        
        return render_template('ml_features/predictions.html', **result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return render_template('ml_features/predictions.html', 
                             predictions=[], 
                             suggestions=[], 
                             total_predicted=0,
                             avg_daily=0,
                             actual_vs_predicted={},
                             error=str(e))


@ml_bp.route('/suggestions')
@login_required_ml
def suggestions():
    """Buying reminders page - simplified"""
    user_id = session.get('user_id')
    if not user_id:
        flash("Please log in to view buying reminders.", "error")
        return redirect(url_for('login'))
    
    try:
        result = ml_service.get_buying_suggestions(user_id, top_n=5)
        item_suggestions = result.get('item_suggestions', [])
        return render_template('ml_features/suggestions.html',
                             item_suggestions=item_suggestions)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return render_template('ml_features/suggestions.html',
                             error=str(e),
                             item_suggestions=[])


@ml_bp.route('/api/predictions')
@login_required_ml
def api_predictions():
    """API endpoint for expense predictions"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'User not logged in'}), 401
    
    days_ahead = request.args.get('days', 7, type=int)
    incremental = request.args.get('incremental', 'true').lower() == 'true'
    
    try:
        result = ml_service.get_expense_predictions(user_id, days_ahead=days_ahead, incremental=incremental)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@ml_bp.route('/api/category-alerts')
@login_required_ml
def category_alerts():
    """Get category spending alerts - which categories are overboard"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'User not logged in'}), 401
    
    try:
        from ml_features.utils.data_loader import get_db
        from bson.objectid import ObjectId
        from datetime import datetime, timedelta
        
        db = get_db()
        user_id_obj = ObjectId(user_id) if isinstance(user_id, str) else user_id
        
        # Get current month expenses
        today = datetime.now()
        current_month_start = today.replace(day=1).strftime('%Y-%m-%d')
        current_month_expenses = list(db.purchases.find({
            "user_id": user_id_obj,
            "date": {"$gte": current_month_start}
        }))
        
        # Get historical average (last 3 months)
        three_months_ago = (today - timedelta(days=90)).strftime('%Y-%m-%d')
        historical_expenses = list(db.purchases.find({
            "user_id": user_id_obj,
            "date": {"$gte": three_months_ago, "$lt": current_month_start}
        }))
        
        # Calculate current month spending by category
        current_by_category = {}
        for exp in current_month_expenses:
            cat = exp.get('category', 'Others')
            current_by_category[cat] = current_by_category.get(cat, 0) + float(exp.get('amount', 0))
        
        # Calculate historical average by category (per month)
        historical_by_category = {}
        for exp in historical_expenses:
            cat = exp.get('category', 'Others')
            historical_by_category[cat] = historical_by_category.get(cat, 0) + float(exp.get('amount', 0))
        
        # Normalize historical to per-month average (assuming 3 months of data)
        for cat in historical_by_category:
            historical_by_category[cat] = historical_by_category[cat] / 3
        
        # Find categories that are overboard (more than 20% above average)
        alerts = []
        days_in_month = today.day
        days_in_avg_month = 30  # Approximate
        
        for cat in current_by_category:
            current = current_by_category[cat]
            avg = historical_by_category.get(cat, 0)
            
            if avg > 0:
                # Project current month spending
                projected = (current / days_in_month) * days_in_avg_month if days_in_month > 0 else current
                
                # Calculate increase percentage
                increase_pct = ((projected - avg) / avg) * 100 if avg > 0 else 0
                
                if increase_pct > 20:  # More than 20% above average
                    excess = projected - avg
                    alerts.append({
                        'category': cat,
                        'current_month': current,
                        'projected_month': projected,
                        'normal_average': avg,
                        'increase_pct': round(increase_pct, 1),
                        'excess_amount': round(excess, 2),
                        'reduce_by': round(excess, 2)  # How much to reduce to get back to normal
                    })
        
        # Sort by excess amount (highest first)
        alerts.sort(key=lambda x: x['excess_amount'], reverse=True)
        
        return jsonify({
            'alerts': alerts,
            'current_month': current_month_start
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'alerts': []}), 500


@ml_bp.route('/api/model/versions')
@login_required_ml
def api_model_versions():
    """API endpoint to get all model versions"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'User not logged in'}), 401
    
    try:
        versions = ml_service.get_model_versions(user_id)
        return jsonify({'versions': versions})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@ml_bp.route('/api/model/accuracy')
@login_required_ml
def api_model_accuracy():
    """API endpoint to get accuracy history"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'User not logged in'}), 401
    
    try:
        history = ml_service.get_accuracy_history(user_id)
        return jsonify({'history': history})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@ml_bp.route('/api/suggestions')
@login_required_ml
def api_suggestions():
    """API endpoint for buying suggestions"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'User not logged in'}), 401
    
    top_n = request.args.get('top', 10, type=int)
    
    try:
        result = ml_service.get_buying_suggestions(user_id, top_n=top_n)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

