"""
Model Manager - Handles model persistence, versioning, and incremental learning
"""

import os
import pickle
import json
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
import xgboost as xgb


class ModelManager:
    def __init__(self, user_id, model_dir="ml_features/models/saved"):
        self.user_id = str(user_id)
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.user_model_dir = self.model_dir / self.user_id
        self.user_model_dir.mkdir(parents=True, exist_ok=True)
        
    def get_model_path(self, version=None):
        """Get path to saved model"""
        if version:
            return self.user_model_dir / f"model_v{version}.pkl"
        return self.user_model_dir / "model_latest.pkl"
    
    def get_metadata_path(self, version=None):
        """Get path to model metadata"""
        if version:
            return self.user_model_dir / f"metadata_v{version}.json"
        return self.user_model_dir / "metadata_latest.json"
    
    def get_encoder_path(self):
        """Get path to category encoder"""
        return self.user_model_dir / "category_encoder.pkl"
    
    def save_model(self, model, category_encoder, metadata):
        """Save model, encoder, and metadata"""
        # Get next version number
        version = self.get_next_version()
        
        # Save model
        model_path = self.get_model_path(version)
        with open(model_path, 'wb') as f:
            pickle.dump(model, f)
        
        # Save latest model
        latest_path = self.get_model_path()
        with open(latest_path, 'wb') as f:
            pickle.dump(model, f)
        
        # Save encoder
        encoder_path = self.get_encoder_path()
        with open(encoder_path, 'wb') as f:
            pickle.dump(category_encoder, f)
        
        # Save metadata
        metadata['version'] = version
        metadata['saved_at'] = datetime.now().isoformat()
        metadata_path = self.get_metadata_path(version)
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        # Save latest metadata
        latest_metadata_path = self.get_metadata_path()
        with open(latest_metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        return version
    
    def load_model(self, version=None):
        """Load model from disk"""
        model_path = self.get_model_path(version)
        if not model_path.exists():
            return None
        
        with open(model_path, 'rb') as f:
            return pickle.load(f)
    
    def load_encoder(self):
        """Load category encoder from disk"""
        encoder_path = self.get_encoder_path()
        if not encoder_path.exists():
            return None
        
        with open(encoder_path, 'rb') as f:
            return pickle.load(f)
    
    def load_metadata(self, version=None):
        """Load model metadata"""
        metadata_path = self.get_metadata_path(version)
        if not metadata_path.exists():
            return None
        
        with open(metadata_path, 'r') as f:
            return json.load(f)
    
    def get_next_version(self):
        """Get next version number"""
        existing_versions = []
        for file in self.user_model_dir.glob("model_v*.pkl"):
            try:
                version = int(file.stem.split('_v')[1])
                existing_versions.append(version)
            except:
                pass
        
        if existing_versions:
            return max(existing_versions) + 1
        return 1
    
    def get_all_versions(self):
        """Get all model versions"""
        versions = []
        for file in self.user_model_dir.glob("metadata_v*.json"):
            try:
                version = int(file.stem.split('_v')[1])
                metadata = self.load_metadata(version)
                if metadata:
                    versions.append({
                        'version': version,
                        **metadata
                    })
            except:
                pass
        
        return sorted(versions, key=lambda x: x.get('version', 0), reverse=True)
    
    def save_prediction_accuracy(self, predictions, actuals):
        """Save prediction accuracy metrics"""
        if not predictions or not actuals:
            return None
        
        # Calculate metrics
        pred_values = [p.get('predicted_amount', 0) for p in predictions]
        actual_values = [a.get('amount', 0) for a in actuals]
        
        if len(pred_values) != len(actual_values):
            return None
        
        mae = mean_absolute_error(actual_values, pred_values)
        rmse = np.sqrt(mean_squared_error(actual_values, pred_values))
        
        accuracy_data = {
            'date': datetime.now().isoformat(),
            'mae': float(mae),
            'rmse': float(rmse),
            'num_predictions': len(predictions),
            'predictions': predictions,
            'actuals': actuals
        }
        
        # Save to accuracy history
        accuracy_file = self.user_model_dir / "accuracy_history.json"
        history = []
        if accuracy_file.exists():
            with open(accuracy_file, 'r') as f:
                history = json.load(f)
        
        history.append(accuracy_data)
        
        # Keep only last 100 entries
        if len(history) > 100:
            history = history[-100:]
        
        with open(accuracy_file, 'w') as f:
            json.dump(history, f, indent=2)
        
        return accuracy_data
    
    def get_accuracy_history(self):
        """Get accuracy history"""
        accuracy_file = self.user_model_dir / "accuracy_history.json"
        if not accuracy_file.exists():
            return []
        
        with open(accuracy_file, 'r') as f:
            return json.load(f)
    
    def get_accuracy_stats(self):
        """Get accuracy statistics"""
        history = self.get_accuracy_history()
        if not history:
            return None
        
        mae_values = [h['mae'] for h in history]
        rmse_values = [h['rmse'] for h in history]
        
        return {
            'total_evaluations': len(history),
            'avg_mae': float(np.mean(mae_values)),
            'avg_rmse': float(np.mean(rmse_values)),
            'best_mae': float(np.min(mae_values)),
            'worst_mae': float(np.max(mae_values)),
            'latest_mae': float(mae_values[-1]) if mae_values else None,
            'trend': 'improving' if len(mae_values) > 1 and mae_values[-1] < mae_values[0] else 'stable'
        }

