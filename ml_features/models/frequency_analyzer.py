"""
Statistical frequency analysis for buying suggestions
Analyzes purchase patterns and suggests items to buy
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import Counter


class FrequencyAnalyzer:
    def __init__(self):
        pass
    
    def analyze_purchase_frequency(self, df):
        """Analyze how often items are purchased"""
        if df.empty:
            return []
        
        # Group by item and category
        item_freq = df.groupby(['item', 'category']).agg({
            'amount': ['count', 'mean', 'sum'],
            'date': ['min', 'max']
        }).reset_index()
        
        item_freq.columns = ['item', 'category', 'frequency', 'avg_amount', 'total_amount', 'first_purchase', 'last_purchase']
        
        # Calculate days since last purchase (using .loc to avoid warnings)
        item_freq = item_freq.copy()
        item_freq.loc[:, 'days_since_last'] = (datetime.now() - pd.to_datetime(item_freq['last_purchase'])).dt.days
        item_freq.loc[:, 'avg_days_between'] = (pd.to_datetime(item_freq['last_purchase']) - pd.to_datetime(item_freq['first_purchase'])).dt.days / item_freq['frequency']
        item_freq.loc[:, 'avg_days_between'] = item_freq['avg_days_between'].fillna(0)
        
        # Calculate purchase probability (if days_since_last > avg_days_between, likely to buy soon)
        item_freq.loc[:, 'purchase_probability'] = item_freq.apply(
            lambda row: min(1.0, row['days_since_last'] / row['avg_days_between']) if row['avg_days_between'] > 0 else 0.5,
            axis=1
        )
        
        return item_freq.sort_values('purchase_probability', ascending=False)
    
    def get_buying_suggestions(self, df, top_n=5):
        """Get buying suggestions based on frequency analysis - simplified and user-friendly"""
        if df.empty:
            return []
        
        freq_analysis = self.analyze_purchase_frequency(df)
        
        if freq_analysis.empty:
            return []
        
        suggestions = []
        
        # Get items that are likely to be needed soon
        # More lenient criteria - items bought at least 2 times
        likely_items = freq_analysis[
            (freq_analysis['frequency'] >= 2)
        ].head(top_n * 2)  # Get more candidates, then filter
        
        for _, row in likely_items.iterrows():
            days_ago = int(row['days_since_last'])
            avg_days = int(row['avg_days_between']) if row['avg_days_between'] > 0 else 0
            
            # Show suggestion if it's time to buy again (80% of average interval)
            if avg_days > 0 and days_ago >= avg_days * 0.8:
                # Create more conversational messaging
                if days_ago >= avg_days * 1.5:
                    message = f"Based on your history, you usually buy this every {avg_days} days. It's been {days_ago} days since your last purchase."
                    prompt = "Want to buy this again?"
                elif days_ago >= avg_days:
                    message = f"You typically buy this every {avg_days} days. Last purchased {days_ago} days ago."
                    prompt = "Time to restock?"
                else:
                    message = f"You usually buy this every {avg_days} days. Last purchased {days_ago} days ago."
                    prompt = "Planning to buy soon?"
                
                suggestion = {
                    'item': row['item'],
                    'category': row['category'],
                    'message': message,
                    'prompt': prompt,
                    'reminder': f'You buy this every {avg_days} days',
                    'last_bought': f'{days_ago} days ago',
                    'amount': round(float(row['avg_amount']), 2),
                    'times_bought': int(row['frequency']),
                    'urgency': 'high' if days_ago >= avg_days else 'medium'
                }
                suggestions.append(suggestion)
                
                # Limit to top_n
                if len(suggestions) >= top_n:
                    break
        
        return suggestions
    
    def get_category_suggestions(self, df):
        """Get category-level buying suggestions"""
        if df.empty:
            return []
        
        # Analyze category spending patterns
        category_analysis = df.groupby('category').agg({
            'amount': ['sum', 'mean', 'count'],
            'date': 'max'
        }).reset_index()
        
        category_analysis.columns = ['category', 'total_spent', 'avg_amount', 'purchase_count', 'last_purchase']
        
        # Calculate days since last purchase in category (using .loc to avoid warnings)
        category_analysis = category_analysis.copy()
        category_analysis.loc[:, 'days_since_last'] = (
            datetime.now() - pd.to_datetime(category_analysis['last_purchase'])
        ).dt.days
        
        # Get categories that haven't been purchased recently
        suggestions = []
        for _, row in category_analysis.iterrows():
            if row['days_since_last'] > 14:  # More than 2 weeks
                suggestions.append({
                    'category': row['category'],
                    'message': f"You haven't purchased from {row['category']} in {int(row['days_since_last'])} days. Average spending: ₹{row['avg_amount']:,.0f}",
                    'avg_amount': round(float(row['avg_amount']), 2),
                    'days_since': int(row['days_since_last'])
                })
        
        return sorted(suggestions, key=lambda x: x['days_since'], reverse=True)

