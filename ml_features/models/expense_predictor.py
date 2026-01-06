"""
XGBoost-based expense prediction model
Predicts future expenses and provides suggestions
Supports model persistence, incremental learning, and accuracy tracking
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import xgboost as xgb
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split
import pickle
import os
from .model_manager import ModelManager


class ExpensePredictor:
    def __init__(self, user_id=None):
        self.user_id = user_id
        self.model = None
        self.category_encoder = LabelEncoder()
        self.is_trained = False
        self.model_manager = ModelManager(user_id) if user_id else None
        self.current_version = None
        
    def train(self, df, incremental=False):
        """Train XGBoost model on expense data with optional incremental learning"""
        if df.empty or len(df) < 10:
            return False
        
        # Try to load existing model for incremental learning
        existing_model = None
        existing_encoder = None
        if incremental and self.model_manager:
            existing_model = self.model_manager.load_model()
            existing_encoder = self.model_manager.load_encoder()
            if existing_model and existing_encoder:
                self.model = existing_model
                self.category_encoder = existing_encoder
        
        # Prepare features
        df = df.copy()
        df = df.sort_values('date')
        
        # Ensure date is datetime
        if not pd.api.types.is_datetime64_any_dtype(df['date']):
            df['date'] = pd.to_datetime(df['date'])
        
        # Add time features if not present
        if 'day_of_week' not in df.columns:
            df['day_of_week'] = df['date'].dt.dayofweek
        if 'day_of_month' not in df.columns:
            df['day_of_month'] = df['date'].dt.day
        if 'month' not in df.columns:
            df['month'] = df['date'].dt.month
        if 'is_weekend' not in df.columns:
            df['is_weekend'] = df['day_of_week'].isin([5, 6]).astype(int)
        
        # Encode categories
        if 'category' in df.columns:
            if existing_encoder:
                # Use existing encoder, handle new categories
                try:
                    df.loc[:, 'category_encoded'] = existing_encoder.transform(df['category'])
                except ValueError:
                    # New categories found, refit encoder
                    df.loc[:, 'category_encoded'] = self.category_encoder.fit_transform(df['category'])
                    self.category_encoder = self.category_encoder
            else:
                df.loc[:, 'category_encoded'] = self.category_encoder.fit_transform(df['category'])
        else:
            return False
        
        # Create features
        features = []
        targets = []
        
        # Use last 7 days to predict next day
        window_size = 7
        
        for i in range(window_size, len(df)):
            window_data = df.iloc[i-window_size:i]
            
            # Features from window
            feature_row = {
                'amount_mean': window_data['amount'].mean(),
                'amount_std': window_data['amount'].std(),
                'amount_max': window_data['amount'].max(),
                'amount_min': window_data['amount'].min(),
                'category_encoded': window_data.iloc[-1]['category_encoded'],
                'day_of_week': df.iloc[i]['day_of_week'],
                'day_of_month': df.iloc[i]['day_of_month'],
                'month': df.iloc[i]['month'],
                'is_weekend': df.iloc[i]['is_weekend'] if 'is_weekend' in df.columns else 0,
            }
            
            # Add category frequency
            category_counts = window_data['category_encoded'].value_counts()
            feature_row['category_freq'] = category_counts.get(window_data.iloc[-1]['category_encoded'], 0) / len(window_data)
            
            features.append(feature_row)
            targets.append(df.iloc[i]['amount'])
        
        if len(features) < 5:
            return False
        
        X = pd.DataFrame(features)
        y = np.array(targets)
        
        # Train model (incremental or from scratch)
        if incremental and existing_model:
            # Incremental learning: update existing model with new data
            # XGBoost supports incremental learning by continuing training
            self.model = existing_model
            # Continue training with new data (adds more trees)
            self.model.fit(X, y, xgb_model=existing_model.get_booster())
        else:
            # Train new model from scratch
            self.model = xgb.XGBRegressor(
                n_estimators=100,
                max_depth=6,
                learning_rate=0.1,
                random_state=42
            )
            self.model.fit(X, y)
        
        self.is_trained = True
        
        # Save model and metadata
        if self.model_manager:
            metadata = {
                'training_samples': len(features),
                'data_range': {
                    'start': df['date'].min().isoformat(),
                    'end': df['date'].max().isoformat()
                },
                'categories': len(self.category_encoder.classes_),
                'incremental': incremental,
                'has_existing_model': existing_model is not None
            }
            self.current_version = self.model_manager.save_model(
                self.model,
                self.category_encoder,
                metadata
            )
        
        return True
    
    def predict(self, df, days_ahead=7):
        """Predict expenses for next N days - day-to-day predictions"""
        if not self.is_trained or df.empty:
            return []
        
        df = df.copy().sort_values('date')
        
        predictions = []
        last_date = df['date'].max()
        
        # Calculate average daily total for suggestions (sum all expenses per day, then average)
        daily_totals = df.groupby('date')['amount'].sum()
        avg_daily = float(daily_totals.mean()) if len(daily_totals) > 0 else 0
        
        # Get recent daily totals for prediction context
        recent_daily = daily_totals.tail(min(7, len(daily_totals)))
        
        if len(recent_daily) < 3:
            return []
        
        # Get category patterns from recent data
        recent_data = df[df['date'] >= recent_daily.index[0]].copy()
        
        # Ensure category_encoded exists
        if 'category_encoded' not in recent_data.columns and 'category' in recent_data.columns:
            recent_data = recent_data.copy()
            try:
                recent_data.loc[:, 'category_encoded'] = self.category_encoder.transform(recent_data['category'])
            except:
                recent_data.loc[:, 'category_encoded'] = self.category_encoder.fit_transform(recent_data['category'])
        
        # Predict for each day ahead
        for day_offset in range(1, days_ahead + 1):
            target_date = last_date + timedelta(days=day_offset)
            
            # Use average of recent daily totals as base
            recent_avg = float(recent_daily.mean()) if len(recent_daily) > 0 else avg_daily
            
            # Prepare features for this specific day
            feature_row = {
                'amount_mean': float(recent_daily.mean()) if len(recent_daily) > 0 else 0,
                'amount_std': float(recent_daily.std()) if len(recent_daily) > 1 else 0,
                'amount_max': float(recent_daily.max()) if len(recent_daily) > 0 else 0,
                'amount_min': float(recent_daily.min()) if len(recent_daily) > 0 else 0,
                'category_encoded': int(recent_data['category_encoded'].mode()[0]) if len(recent_data) > 0 and 'category_encoded' in recent_data.columns else 0,
                'day_of_week': target_date.weekday(),
                'day_of_month': target_date.day,
                'month': target_date.month,
                'is_weekend': 1 if target_date.weekday() >= 5 else 0,
            }
            
            # Category frequency (most common category in recent data)
            if 'category_encoded' in recent_data.columns and len(recent_data) > 0:
                category_counts = recent_data['category_encoded'].value_counts()
                most_common_cat = category_counts.index[0] if len(category_counts) > 0 else 0
                feature_row['category_freq'] = float(category_counts.get(most_common_cat, 0) / len(recent_data)) if len(recent_data) > 0 else 0
            else:
                feature_row['category_freq'] = 0
            
            X_pred = pd.DataFrame([feature_row])
            try:
                model_pred = float(self.model.predict(X_pred)[0])
                pred_amount = max(0, model_pred)  # Ensure non-negative
                
                # If model predicts 0 or very low value, use recent average as fallback
                if pred_amount < 10 and recent_avg > 0:
                    # Use recent average if model prediction is too low
                    pred_amount = recent_avg * 0.8  # Slightly lower than average for conservative prediction
            except Exception as e:
                # Fallback to recent average if prediction fails
                pred_amount = recent_avg if recent_avg > 0 else avg_daily
            
            # Get likely categories for this day (top categories from similar days)
            # Find similar days (same day of week) in recent data
            similar_days = recent_data[recent_data['day_of_week'] == target_date.weekday()]
            if len(similar_days) > 0:
                # Calculate category proportions from similar days
                category_totals = similar_days.groupby('category')['amount'].sum()
                total_similar = category_totals.sum()
                if total_similar > 0:
                    category_proportions = (category_totals / total_similar).sort_values(ascending=False)
                    # Get top 3 categories and apply proportions to predicted amount
                    top_categories = {}
                    for cat, prop in category_proportions.head(3).items():
                        top_categories[cat] = pred_amount * prop
                    predicted_category = category_proportions.index[0] if len(category_proportions) > 0 else 'Others'
                else:
                    # Fallback
                    if 'category' in recent_data.columns and len(recent_data) > 0:
                        category_mode = recent_data['category'].mode()
                        predicted_category = category_mode[0] if len(category_mode) > 0 else 'Others'
                        top_categories = {predicted_category: pred_amount * 0.4}
                    else:
                        predicted_category = 'Others'
                        top_categories = {}
            else:
                # Fallback to overall most common category
                if 'category' in recent_data.columns and len(recent_data) > 0:
                    category_mode = recent_data['category'].mode()
                    predicted_category = category_mode[0] if len(category_mode) > 0 else 'Others'
                    top_categories = {predicted_category: pred_amount * 0.4}
                else:
                    predicted_category = 'Others'
                    top_categories = {}
            
            predictions.append({
                'date': target_date.strftime('%Y-%m-%d'),
                'day_name': target_date.strftime('%A'),  # Monday, Tuesday, etc.
                'predicted_amount': round(float(pred_amount), 2),
                'category': predicted_category,
                'top_categories': {k: round(v, 2) for k, v in top_categories.items()},  # Breakdown by category
                'confidence': 'medium'
            })
        
        return predictions
    
    def _get_prediction_suggestion(self, pred_amount, avg_daily, category, recent_data):
        """Generate a suggestion for a specific prediction - iPhone-style notification"""
        if pred_amount > avg_daily * 1.5:
            # High spending day - PEAK DETECTED
            increase_pct = ((pred_amount/avg_daily - 1) * 100)
            if category in ['Food & Dining', 'Entertainment', 'Shopping']:
                return {
                    'type': 'warning',
                    'title': f'📈 Spending Peak: {category}',
                    'message': f'Your {category} spending is {increase_pct:.0f}% above average today',
                    'action': f'Predicted: ₹{pred_amount:,.0f} vs Average: ₹{avg_daily:,.0f}',
                    'tips': self._get_category_quick_tips(category, pred_amount, avg_daily),
                    'is_peak': True,
                    'peak_category': category,
                    'peak_amount': pred_amount,
                    'avg_amount': avg_daily
                }
            else:
                return {
                    'type': 'warning',
                    'title': '📈 Spending Peak Detected',
                    'message': f'Your spending is {increase_pct:.0f}% above average today',
                    'action': f'Predicted: ₹{pred_amount:,.0f} vs Average: ₹{avg_daily:,.0f}',
                    'tips': ['Check if all expenses are necessary', 'Look for alternatives', 'Plan ahead for this day'],
                    'is_peak': True,
                    'peak_category': category,
                    'peak_amount': pred_amount,
                    'avg_amount': avg_daily
                }
        elif pred_amount < avg_daily * 0.7:
            return {
                'type': 'success',
                'title': '✅ On Track',
                'message': f'Your spending is below average - great job!',
                'action': f'Predicted: ₹{pred_amount:,.0f} vs Average: ₹{avg_daily:,.0f}',
                'tips': ['Keep tracking expenses', 'Consider saving the difference'],
                'is_peak': False
            }
        else:
            return {
                'type': 'info',
                'title': '✅ On Track',
                'message': f'Your spending aligns with your average',
                'action': f'Predicted: ₹{pred_amount:,.0f}',
                'tips': ['Stay within budget', 'Track as you spend'],
                'is_peak': False
            }
    
    def _get_category_quick_tips(self, category, pred_amount, avg_daily):
        """Get quick tips for a category"""
        if category == 'Food & Dining':
            return [
                'Cook at home instead - save ₹{:.0f}'.format(pred_amount * 0.4),
                'Limit to one meal out',
                'Use meal prep for the day'
            ]
        elif category == 'Entertainment':
            return [
                'Look for free alternatives',
                'Share costs with friends',
                'Set a limit of ₹{:.0f}'.format(avg_daily * 0.8)
            ]
        elif category == 'Shopping':
            return [
                'Wait 24 hours before buying',
                'Check for sales and discounts',
                'Consider if it\'s essential'
            ]
        else:
            return [
                'Review if necessary',
                'Look for cheaper options',
                'Set a spending limit'
            ]
    
    def get_suggestions(self, df, predictions):
        """Generate simple, actionable self-improvement suggestions"""
        if df.empty or not predictions:
            return []
        
        suggestions = []
        
        try:
            # Calculate average spending
            avg_daily = float(df['amount'].mean())
            
            # Calculate weekly average
            if 'date' in df.columns:
                df_copy = df.copy()
                if not pd.api.types.is_datetime64_any_dtype(df_copy['date']):
                    df_copy['date'] = pd.to_datetime(df_copy['date'])
                weekly_totals = df_copy.groupby(df_copy['date'].dt.isocalendar().week)['amount'].sum()
                avg_weekly = float(weekly_totals.mean()) if len(weekly_totals) > 0 else avg_daily * 7
            else:
                avg_weekly = avg_daily * 7
            
            # Predictions summary
            predicted_total = sum(p['predicted_amount'] for p in predictions)
            predicted_weekly = predicted_total / (len(predictions) / 7) if len(predictions) > 0 else 0
            predicted_daily = predicted_total / len(predictions) if len(predictions) > 0 else 0
            
            # Analyze prediction patterns
            pred_amounts = [p['predicted_amount'] for p in predictions]
            max_pred_day = max(pred_amounts) if pred_amounts else 0
            min_pred_day = min(pred_amounts) if pred_amounts else 0
            high_spending_days = [p for p in predictions if p['predicted_amount'] > avg_daily * 1.5]
            
        except Exception as e:
            # Fallback if calculations fail
            avg_daily = float(df['amount'].mean()) if not df.empty else 0
            avg_weekly = avg_daily * 7
            predicted_total = sum(p['predicted_amount'] for p in predictions)
            predicted_weekly = predicted_total / (len(predictions) / 7) if len(predictions) > 0 else 0
            predicted_daily = predicted_total / len(predictions) if len(predictions) > 0 else 0
            max_pred_day = 0
            min_pred_day = 0
            high_spending_days = []
        
        # ===== SUGGESTION 1: Overall Spending Trend Analysis =====
        if predicted_weekly > avg_weekly * 1.3:
            excess = predicted_weekly - avg_weekly
            suggestions.append({
                'type': 'warning',
                'title': '⚠️ High Spending Alert',
                'message': f'Your predicted spending (₹{predicted_weekly:,.0f}/week) is {((predicted_weekly/avg_weekly - 1) * 100):.0f}% higher than your average (₹{avg_weekly:,.0f}/week). You may overspend by ₹{excess:,.0f} this week.',
                'action': 'Review upcoming expenses',
                'improvement': [
                    'Identify which days have highest predicted spending',
                    'Consider postponing non-essential purchases',
                    'Set a weekly budget limit of ₹{:.0f}'.format(avg_weekly * 1.1),
                    'Track expenses daily to stay within budget'
                ]
            })
        elif predicted_weekly > avg_weekly * 1.1:
            suggestions.append({
                'type': 'warning',
                'title': '📈 Above Average Spending',
                'message': f'Your predicted spending (₹{predicted_weekly:,.0f}/week) is slightly above average (₹{avg_weekly:,.0f}/week). Monitor your expenses closely.',
                'action': 'Track daily spending',
                'improvement': [
                    'Review your spending patterns',
                    'Identify areas where you can cut back',
                    'Set reminders for budget limits'
                ]
            })
        elif predicted_weekly < avg_weekly * 0.7:
            savings = avg_weekly - predicted_weekly
            suggestions.append({
                'type': 'success',
                'title': '✅ Excellent Spending Control',
                'message': f'Your predicted spending (₹{predicted_weekly:,.0f}/week) is {((1 - predicted_weekly/avg_weekly) * 100):.0f}% below average. You could save ₹{savings:,.0f} this week!',
                'action': 'Maintain this pattern',
                'improvement': [
                    'Consider saving the difference',
                    'Review what helped you spend less',
                    'Apply these strategies to other weeks'
                ]
            })
        else:
            suggestions.append({
                'type': 'success',
                'title': '✅ On Track',
                'message': f'Your predicted spending (₹{predicted_weekly:,.0f}/week) aligns with your average. You\'re maintaining a consistent spending pattern.',
                'action': 'Keep monitoring',
                'improvement': [
                    'Continue tracking expenses',
                    'Look for opportunities to optimize',
                    'Consider setting savings goals'
                ]
            })
        
        # ===== SUGGESTION 2: Personal High Spending Days (Based on YOUR patterns) =====
        if high_spending_days:
            high_days_list = ', '.join([p['date'] for p in high_spending_days[:3]])
            # Personal message based on their average
            suggestions.append({
                'type': 'warning',
                'title': '📅 You Have Some High-Spending Days Coming',
                'message': f'Based on your spending patterns, you usually spend ₹{avg_daily:,.0f}/day. But on {len(high_spending_days)} days ({high_days_list}), you\'re predicted to spend more than ₹{avg_daily * 1.5:,.0f}.',
                'improvement': [
                    'Review what\'s planned for these specific days',
                    'Your normal daily spending is ₹{:.0f} - try to stay close to this'.format(avg_daily),
                    'Consider if some expenses can be postponed',
                    'Set alerts for these days to track as you spend'
                ]
            })
        
        # ===== SUGGESTION 3: Category Analysis & Optimization with Past Comparison =====
        try:
            if 'category' in df.columns and 'date' in df.columns:
                df_copy = df.copy()
                if not pd.api.types.is_datetime64_any_dtype(df_copy['date']):
                    df_copy['date'] = pd.to_datetime(df_copy['date'])
                
                # Split data into past (first half) and recent (second half)
                df_copy = df_copy.sort_values('date')
                mid_point = len(df_copy) // 2
                if mid_point > 0:
                    past_data = df_copy.iloc[:mid_point]
                    recent_data = df_copy.iloc[mid_point:]
                    
                    # Calculate category spending in past vs recent
                    past_category_totals = past_data.groupby('category')['amount'].sum()
                    recent_category_totals = recent_data.groupby('category')['amount'].sum()
                    
                    # Calculate time periods for comparison
                    past_days = (past_data['date'].max() - past_data['date'].min()).days + 1
                    recent_days = (recent_data['date'].max() - recent_data['date'].min()).days + 1
                    
                    # Normalize to per-day spending
                    past_category_daily = past_category_totals / past_days if past_days > 0 else past_category_totals
                    recent_category_daily = recent_category_totals / recent_days if recent_days > 0 else recent_category_totals
                    
                    # Find categories with significant increases
                    increased_categories = []
                    for cat in recent_category_daily.index:
                        if cat in past_category_daily.index:
                            past_avg = past_category_daily[cat]
                            recent_avg = recent_category_daily[cat]
                            if past_avg > 0:
                                increase_pct = ((recent_avg - past_avg) / past_avg) * 100
                                if increase_pct > 20:  # More than 20% increase
                                    increased_categories.append({
                                        'category': cat,
                                        'past_avg': past_avg,
                                        'recent_avg': recent_avg,
                                        'increase_pct': increase_pct,
                                        'past_total': past_category_totals.get(cat, 0),
                                        'recent_total': recent_category_totals.get(cat, 0)
                                    })
                    
                    # Sort by increase percentage
                    increased_categories.sort(key=lambda x: x['increase_pct'], reverse=True)
                    
                    # Suggest cutting down on non-essential categories that increased
                    non_essential_categories = ['Food & Dining', 'Entertainment', 'Shopping', 'Travel', 'Others']
                    for cat_info in increased_categories[:2]:  # Top 2 increased categories
                        cat = cat_info['category']
                        if cat in non_essential_categories or cat_info['increase_pct'] > 30:
                            suggestions.append({
                                'type': 'warning',
                                'title': f'📈 {cat} Spending Increased',
                                'message': f'Your {cat} spending has increased by {cat_info["increase_pct"]:.0f}% compared to the past. Recent: ₹{cat_info["recent_avg"]*7:,.0f}/week vs Past: ₹{cat_info["past_avg"]*7:,.0f}/week.',
                                'improvement': self._get_category_improvement_tips(cat, cat_info)
                            })
                
                # Analyze category spending
                category_totals = df.groupby('category')['amount'].sum().sort_values(ascending=False)
                category_avg = df.groupby('category')['amount'].mean().sort_values(ascending=False)
                
                # Predict category spending
                pred_by_category = {}
                for pred in predictions:
                    cat = pred.get('category', 'Others')
                    pred_by_category[cat] = pred_by_category.get(cat, 0) + pred['predicted_amount']
                
                top_category = category_totals.index[0] if len(category_totals) > 0 else None
                top_pred_category = max(pred_by_category.items(), key=lambda x: x[1])[0] if pred_by_category else None
                
                if top_category:
                    category_spent = category_totals[top_category]
                    category_percentage = (category_spent / category_totals.sum()) * 100
                    
                    if category_percentage > 40:
                        suggestions.append({
                            'type': 'warning',
                            'title': '🎯 Category Concentration Risk',
                            'message': f'{top_category} accounts for {category_percentage:.0f}% of your total spending (₹{category_spent:,.0f}). This creates a concentration risk.',
                            'action': 'Diversify spending',
                            'improvement': [
                                'Review if all {0} expenses are necessary'.format(top_category),
                                'Look for alternatives or cheaper options',
                                'Consider spreading purchases over time',
                                'Set a monthly limit for {0}'.format(top_category)
                            ]
                        })
                    elif top_pred_category and top_pred_category in pred_by_category:
                        pred_amount = pred_by_category[top_pred_category]
                        suggestions.append({
                            'type': 'info',
                            'title': '📊 Top Spending Category',
                            'message': f'{top_pred_category} is your highest predicted category (₹{pred_amount:,.0f} in next 7 days). Your average in this category is ₹{category_avg.get(top_pred_category, 0):,.0f}.',
                            'action': 'Monitor this category',
                            'improvement': [
                                'Compare predicted vs actual spending',
                                'Set category-specific budgets',
                                'Look for bulk purchase opportunities',
                                'Track if this category is increasing'
                            ]
                        })
        except Exception:
            pass  # Skip if category analysis fails
        
        # ===== SUGGESTION 4: Spending Consistency Analysis =====
        try:
            if 'date' in df.columns:
                df_copy = df.copy()
                if not pd.api.types.is_datetime64_any_dtype(df_copy['date']):
                    df_copy['date'] = pd.to_datetime(df_copy['date'])
                
                # Calculate spending variance
                daily_totals = df_copy.groupby(df_copy['date'].dt.date)['amount'].sum()
                spending_variance = float(daily_totals.std())
                spending_consistency = 'consistent' if spending_variance < avg_daily * 0.5 else 'variable'
                
                if spending_consistency == 'variable':
                    suggestions.append({
                        'type': 'info',
                        'title': '📉 Variable Spending Pattern',
                        'message': f'Your spending varies significantly (std: ₹{spending_variance:,.0f}). Some days you spend much more than others.',
                        'action': 'Smooth out spending',
                        'improvement': [
                            'Identify what causes high-spending days',
                            'Plan expenses more evenly throughout the week',
                            'Set daily spending limits',
                            'Build an emergency fund for unexpected expenses'
                        ]
                    })
                else:
                    suggestions.append({
                        'type': 'success',
                        'title': '📊 Consistent Spending',
                        'message': 'Your spending is relatively consistent, which makes budgeting easier.',
                        'action': 'Maintain consistency',
                        'improvement': [
                            'Continue tracking daily',
                            'Use consistency to plan better',
                            'Consider automated savings'
                        ]
                    })
        except Exception:
            pass
        
        # ===== SUGGESTION 5: Weekend vs Weekday Analysis =====
        try:
            if 'is_weekend' in df.columns or 'day_of_week' in df.columns:
                df_copy = df.copy()
                if 'day_of_week' in df_copy.columns:
                    df_copy['is_weekend'] = df_copy['day_of_week'].isin([5, 6]).astype(int)
                
                weekend_spending = float(df_copy[df_copy['is_weekend'] == 1]['amount'].mean()) if len(df_copy[df_copy['is_weekend'] == 1]) > 0 else 0
                weekday_spending = float(df_copy[df_copy['is_weekend'] == 0]['amount'].mean()) if len(df_copy[df_copy['is_weekend'] == 0]) > 0 else 0
                
                if weekend_spending > weekday_spending * 1.3:
                    suggestions.append({
                        'type': 'info',
                        'title': '🎉 Weekend Spending Pattern',
                        'message': f'You spend {((weekend_spending/weekday_spending - 1) * 100):.0f}% more on weekends (₹{weekend_spending:,.0f}) than weekdays (₹{weekday_spending:,.0f}).',
                        'action': 'Plan weekend budgets',
                        'improvement': [
                            'Set a weekend spending limit',
                            'Plan weekend activities in advance',
                            'Look for free or low-cost weekend alternatives',
                            'Balance weekend fun with weekday savings'
                        ]
                    })
        except Exception:
            pass
        
        # ===== SUGGESTION 6: Savings Opportunity =====
        if predicted_weekly < avg_weekly:
            potential_savings = avg_weekly - predicted_weekly
            monthly_savings = potential_savings * 4
            suggestions.append({
                'type': 'success',
                'title': '💰 Savings Opportunity',
                'message': f'If you maintain this spending level, you could save ₹{potential_savings:,.0f} this week (₹{monthly_savings:,.0f}/month).',
                'action': 'Set savings goal',
                'improvement': [
                    'Automatically transfer savings to a separate account',
                    'Set up a recurring savings goal',
                    'Track your savings progress',
                    'Reward yourself when you hit savings milestones'
                ]
            })
        
        # ===== SUGGESTION 7: Daily Budget Recommendation =====
        optimal_daily = avg_daily if avg_daily > 0 else predicted_daily
        suggestions.append({
            'type': 'info',
            'title': '📋 Daily Budget Recommendation',
            'message': f'Based on your spending patterns, aim for ₹{optimal_daily:,.0f} per day. Your predicted average is ₹{predicted_daily:,.0f}/day.',
            'action': 'Set daily limit',
            'improvement': [
                'Use daily budget alerts',
                'Track expenses as you spend',
                'Adjust budget based on your goals',
                'Review and update budget monthly'
            ]
        })
        
        return suggestions
    
    def _get_category_improvement_tips(self, category, cat_info):
        """Get personalized improvement tips based on category"""
        tips = []
        
        if category == 'Food & Dining':
            tips = [
                'Cook at home more often - save ₹{:.0f}/week'.format(cat_info['recent_avg'] * 7 * 0.3),
                'Limit dining out to weekends only',
                'Use meal prep to reduce food expenses',
                'Look for restaurant deals and discounts',
                'Pack lunch instead of eating out'
            ]
        elif category == 'Entertainment':
            tips = [
                'Look for free entertainment options',
                'Share streaming subscriptions with family',
                'Set a monthly entertainment budget of ₹{:.0f}'.format(cat_info['recent_avg'] * 30 * 0.7),
                'Prioritize experiences over material purchases',
                'Use library services for books and movies'
            ]
        elif category == 'Shopping':
            tips = [
                'Wait 24 hours before making non-essential purchases',
                'Create a shopping list and stick to it',
                'Look for sales and discounts before buying',
                'Consider buying second-hand for some items',
                'Set a monthly shopping limit of ₹{:.0f}'.format(cat_info['recent_avg'] * 30 * 0.8)
            ]
        elif category == 'Travel':
            tips = [
                'Plan trips in advance for better deals',
                'Use travel rewards and points',
                'Consider staycations or local travel',
                'Book flights and hotels during off-peak seasons',
                'Set a travel budget and stick to it'
            ]
        elif category == 'Transport':
            tips = [
                'Use public transport when possible',
                'Carpool or share rides',
                'Walk or cycle for short distances',
                'Plan routes to minimize fuel consumption',
                'Consider fuel-efficient vehicles for long-term savings'
            ]
        else:
            tips = [
                'Review all {0} expenses for necessity'.format(category),
                'Look for cheaper alternatives',
                'Set a monthly budget for {0}'.format(category),
                'Track spending in this category weekly',
                'Identify which {0} expenses can be reduced'.format(category)
            ]
        
        return tips

