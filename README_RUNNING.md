# How to Run HouseWise

## Quick Start

### Option 1: Using the run script (Recommended)
```bash
./run.sh
```

### Option 2: Manual activation
```bash
# Activate virtual environment
source venv/bin/activate

# Run the app
python3 app.py
```

## Important Notes

1. **Always activate the virtual environment first**
   - The app requires packages installed in `venv/`
   - Without activation, you'll get `ModuleNotFoundError`

2. **App runs on port 5002**
   - Access at: http://localhost:5002
   - Not the default port 5000

3. **Database Connection**
   - Default: `mongodb://localhost:27017/sem5`
   - Make sure MongoDB is running
   - Set `MONGO_URI` in `.env` if using a different database

## Troubleshooting

### Error: `ModuleNotFoundError: No module named 'cv2'`
**Solution**: Activate the virtual environment first
```bash
source venv/bin/activate
```

### Error: `Connection refused` (MongoDB)
**Solution**: Start MongoDB service
```bash
# macOS (if installed via Homebrew)
brew services start mongodb-community

# Or check if MongoDB is running
mongosh
```

### Port already in use
**Solution**: Change port in `app.py` line 2967:
```python
app.run(debug=True, port=5003)  # Use different port
```

## Development Mode

The app runs in debug mode by default:
- Auto-reloads on code changes
- Detailed error messages
- Debug toolbar (if enabled)

## Production Mode

For production, set environment variables:
```bash
export FLASK_ENV=production
export SECRET_KEY=your-secret-key-here
export MONGO_URI=your-mongodb-uri
```

Then run:
```bash
python3 app.py
```

