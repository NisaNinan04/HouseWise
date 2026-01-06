import os
import cv2
import numpy as np
import easyocr
import re
import fitz
import warnings
import pickle
import base64
import atexit
from PIL import Image
from datetime import datetime, date, timedelta, timezone
from dateutil.relativedelta import relativedelta
from dateutil.parser import parse
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson.objectid import ObjectId
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_pymongo import PyMongo
from flask_login import login_required, current_user
# Note: Using custom session implementation for MongoDB-based sessions
from dotenv import load_dotenv
from functools import wraps
from flask_mail import Mail, Message
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from apscheduler.schedulers.background import BackgroundScheduler
from email.mime.text import MIMEText
from bs4 import BeautifulSoup

# Import finance module functionality
from finance.summary import (
    total_income_vs_expense,
    expense_breakdown_by_subcategory,
    monthly_cashflow,
    spending_segments,
    last_30_days_segments,
    last_30_days_breakdown,
    regular_spending_count,
    top_3_categories,
    cashflow_status,
)
from finance.data_model import get_db, ensure_indexes, normalize_user_id
from finance.classification import classify_transaction, load_categories_config

# APScheduler (and other packages) may emit a UserWarning about pkg_resources deprecation.
# Filter that specific warning to avoid noisy startup logs. This should be kept minimal
# and only target the exact message to avoid hiding other important warnings.
warnings.filterwarnings(
    "ignore",
    message=r"pkg_resources is deprecated as an API.*",
    category=UserWarning,
)

GMAIL_SEND_SCOPES = ['https://www.googleapis.com/auth/gmail.send']
GMAIL_READ_SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
TOKEN_FILE = 'token.json'
CREDS_FILE = 'credentials.json'

# Load environment variables from .env file
load_dotenv()

# Initialize PyMongo and ensure indexes
mongo = PyMongo()
ensure_indexes()

# Globals for file uploads and EasyOCR
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs('static/uploads', exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}

# Initialize EasyOCR reader lazily to avoid blocking startup
_ocr_reader = None
def get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        _ocr_reader = easyocr.Reader(['en'])
    return _ocr_reader

family_members = ["Noela", "Nisa", "Shreya", "Snowfiya"]

# Decorator to check if a user is logged in
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Helper function to check allowed file extensions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Auto-category detection using rule-based keyword matching
def detect_category_from_item(item_name, item_type='expense', amount=0.0):
    """
    Rule-based keyword matching for auto category selection
    Uses finance/classification.py system for consistency
    Returns category based on item name keywords and rules
    """
    if not item_name:
        return None
    
    try:
        # Use the existing classification system
        from finance.classification import classify_transaction
        category, subcategory = classify_transaction(item_name, amount)
        
        # Map the classification system categories to our expense categories
        if item_type == 'expense':
            category_mapping = {
                'Expense': {
                    'Food & Dining': 'Food & Dining',
                    'Groceries': 'Groceries',
                    'Shopping': 'Shopping',
                    'Transport': 'Transport',
                    'Bills': 'Bills & Utilities',
                    'Subscriptions': 'Entertainment',
                    'Medicine': 'Healthcare',
                    'Rent': 'Housing',
                    'Others': 'Others'
                },
                'Investment': 'Investments',
                'Taxes': 'Others'
            }
            
            # If we got a subcategory, try to map it
            if subcategory and category == 'Expense':
                mapped = category_mapping.get('Expense', {}).get(subcategory)
                if mapped:
                    return mapped
            
            # Fallback to direct category mapping
            if category in category_mapping:
                if isinstance(category_mapping[category], dict):
                    return 'Others'  # Default for Expense category without subcategory
                return category_mapping[category]
            
            return 'Others'
        else:
            # Income categories
            income_mapping = {
                'Income': 'Salary',
                'Salary': 'Salary',
                'Others': 'Others'
            }
            return income_mapping.get(category, 'Others')
            
    except Exception as e:
        # Fallback to simple keyword matching if classification fails
        import logging
        logging.warning(f"Classification failed, using fallback: {e}")
        return detect_category_fallback(item_name, item_type)


def detect_category_fallback(item_name, item_type='expense'):
    """
    Fallback keyword matching if classification system fails
    """
    if not item_name:
        return None
    
    item_lower = item_name.lower()
    
    # Expense categories with keywords (comprehensive list)
    if item_type == 'expense':
        category_keywords = {
            'Groceries': ['grocery', 'supermarket', 'vegetable', 'fruit', 'milk', 'bread', 'rice', 'wheat', 'dal', 'pulses', 'spices', 'oil', 'ghee', 'butter', 'cheese', 'egg', 'chicken', 'meat', 'fish', 'snacks', 'biscuit', 'chips', 'namkeen', 'bigbasket', 'dmart', 'grocer'],
            'Food & Dining': ['restaurant', 'cafe', 'dining', 'food', 'pizza', 'burger', 'coffee', 'tea', 'breakfast', 'lunch', 'dinner', 'hotel', 'zomato', 'swiggy', 'uber eats', 'ubereats', 'foodpanda', 'dominos', 'kfc', 'mcdonald', 'mcdonalds'],
            'Transport': ['uber', 'ola', 'taxi', 'cab', 'auto', 'rickshaw', 'metro', 'bus', 'train', 'flight', 'airport', 'petrol', 'diesel', 'fuel', 'gas', 'parking', 'toll', 'transport', 'rapido'],
            'Shopping': ['amazon', 'flipkart', 'myntra', 'shopping', 'clothes', 'dress', 'shirt', 'pant', 'shoes', 'bag', 'watch', 'jewelry', 'electronics', 'mobile', 'phone', 'laptop', 'headphone', 'speaker'],
            'Bills & Utilities': ['electricity', 'water', 'internet', 'wifi', 'broadband', 'phone bill', 'mobile bill', 'landline', 'utility', 'bill', 'payment', 'recharge', 'prepaid', 'postpaid', 'water bill'],
            'Entertainment': ['movie', 'cinema', 'theater', 'netflix', 'prime', 'hotstar', 'spotify', 'youtube', 'music', 'game', 'gaming', 'entertainment', 'party', 'event', 'concert'],
            'Healthcare': ['medicine', 'pharmacy', 'medical', 'doctor', 'hospital', 'clinic', 'health', 'tablet', 'syrup', 'injection', 'test', 'lab', 'diagnostic', 'apollo', 'fortis'],
            'Education': ['school', 'college', 'university', 'tuition', 'course', 'book', 'stationery', 'pen', 'pencil', 'notebook', 'education', 'fee', 'exam'],
            'Personal Care': ['salon', 'spa', 'beauty', 'cosmetic', 'shampoo', 'soap', 'toothpaste', 'cream', 'lotion', 'parlor', 'grooming', 'haircut'],
            'Travel': ['travel', 'trip', 'vacation', 'holiday', 'hotel', 'booking', 'airbnb', 'makemytrip', 'goibibo', 'yatra'],
            'Investments': ['investment', 'mutual fund', 'mutual', 'mf', 'stocks', 'sip', 'fd', 'rd', 'savings', 'equity', 'bond', 'nifty', 'zerodha'],
            'Housing': ['rent', 'landlord', 'housing', 'mortgage']
        }
        
        # Check each category for keyword matches
        for category, keywords in category_keywords.items():
            for keyword in keywords:
                if keyword in item_lower:
                    return category
        
        return 'Others'
    else:
        # Income categories
        income_keywords = {
            'Salary': ['salary', 'pay', 'wage', 'payroll', 'employment'],
            'Freelance': ['freelance', 'freelancing', 'contract', 'project', 'consulting'],
            'Business': ['business', 'sales', 'revenue', 'profit'],
            'Investment Returns': ['dividend', 'interest', 'return', 'gain'],
            'Rental Income': ['rent', 'rental', 'property']
        }
        
        for category, keywords in income_keywords.items():
            for keyword in keywords:
                if keyword in item_lower:
                    return category
        
        return 'Others'

# Gmail token management
def get_gmail_token_path(email_id=None, for_sending=True):
    """Get the appropriate token file path based on email and permission type"""
    if email_id:
        suffix = '_send' if for_sending else '_read'
        return f"token_{email_id.replace('@', '_').replace('.', '_')}{suffix}.json"
    return TOKEN_FILE

def get_gmail_credentials(email_id=None, for_sending=True):
    """Get Gmail credentials with appropriate scopes"""
    token_file = get_gmail_token_path(email_id, for_sending)
    scopes = GMAIL_SEND_SCOPES if for_sending else GMAIL_READ_SCOPES
    creds = None
    
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, scopes)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, scopes)
            creds = flow.run_local_server(port=0)
            with open(token_file, "w") as token:
                token.write(creds.to_json())
    
    return creds

# Gmail helper functions
def get_gmail_readonly_service(email_id=None):
    """Get Gmail service with read-only permissions"""
    if not os.path.exists(CREDS_FILE):
        raise FileNotFoundError(f"Gmail credentials file not found: {CREDS_FILE}")
    
    token_file = TOKEN_FILE if not email_id else f"token_{email_id.replace('@', '_').replace('.', '_')}.json"
    creds = None
    
    if os.path.exists(token_file):
        try:
            creds = Credentials.from_authorized_user_file(token_file, GMAIL_READ_SCOPES)
        except Exception as e:
            print(f"Error loading existing token: {e}")
            creds = None
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Error refreshing token: {e}")
                creds = None
        
        if not creds or not creds.valid:
            try:
                flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, GMAIL_READ_SCOPES)
                creds = flow.run_local_server(port=0)
                with open(token_file, "w") as token:
                    token.write(creds.to_json())
            except Exception as e:
                print(f"Error during OAuth flow: {e}")
                raise Exception(f"Failed to authenticate with Gmail: {str(e)}")
    
    if not creds or not creds.valid:
        raise Exception("Invalid Gmail credentials")
    
    return build("gmail", "v1", credentials=creds)

def gmail_search_messages(service, query, max_results=50):
    """Search for messages in Gmail"""
    try:
        results = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        messages = results.get("messages", [])
        print(f"Gmail API returned {len(messages)} messages for query: {query}")
        return messages
    except Exception as e:
        print(f"Error searching messages: {e}")
        import traceback
        print(traceback.format_exc())
        return None

def gmail_get_message_body(service, msg_id):
    """Get the body content of a Gmail message"""
    try:
        msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        payload = msg["payload"]
        parts = payload.get("parts")
        data = None

        if parts:
            for part in parts:
                if part["mimeType"] == "text/html":
                    data = part["body"]["data"]
                    break
                elif part["mimeType"] == "text/plain":
                    data = part["body"]["data"]
                    break
        else:
            data = payload["body"]["data"]

        if data:
            decoded_data = base64.urlsafe_b64decode(data).decode("utf-8")
            return decoded_data
        return None
    except Exception as e:
        print(f"Error getting message body: {e}")
        return None

def extract_order_details(email_html):
    """Extract order details from email HTML content"""
    soup = BeautifulSoup(email_html, "html.parser")
    text = soup.get_text()

    order_id_match = re.search(r"Order\s*#\s*(\w+)", text)
    total_match = re.search(r"₹[\d,]+", text)
    date_match = re.search(r"(?:Placed on|Ordered on|Date):?\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})", text)

    order_id = order_id_match.group(1) if order_id_match else "N/A"
    total_amount = total_match.group(0) if total_match else "N/A"
    order_date = date_match.group(1) if date_match else "N/A"

    return {
        "Order ID": order_id,
        "Total": total_amount,
        "Date": order_date
    }

# Helper function to parse date from text
def parse_date_from_text(text):
    try:
        match = re.search(r'(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4}[-/]\d{2}[-/]\d{2}|\d{1,2} [A-Za-z]+ \d{4}|[A-Za-z]+ \d{1,2}, \d{4})', text)
        if match:
            dt = parse(match.group(), dayfirst=True)
            return dt.strftime('%Y-%m-%d')
    except:
        pass
    return date.today().strftime('%Y-%m-%d')

# Helper function to extract summary from receipt text
def extract_summary_from_text(text):
    lines = text.split('\n')
    company_name = "Unknown Company"
    total_amount = 0.0
    total_values = []

    # Guess company name
    potential_company_lines = lines[:5]
    company_keywords = ["bazar", "mart", "store", "shop", "groceries", "supermarket", "ltm", "limited"]
    for line in potential_company_lines:
        line = line.strip()
        if not line or len(line.split()) < 2:
            continue
        if re.search(r'\d{1,2}[-/]\d{1,2}[-/]\d{2,4}', line):
            continue
        if any(keyword in line.lower() for keyword in company_keywords) or line.isupper():
            company_name = line
            break
        if company_name == "Unknown Company":
            company_name = line

    # Find totals
    all_total_keywords = ["net amt", "grand total", "total amount payable", "total amount", "net total", "total", "payable", "balance", "amt"]
    for i, line in enumerate(lines):
        line_lower = line.lower()
        for keyword in all_total_keywords:
            if keyword in line_lower:
                price_matches = re.findall(r'(\d+(?:,\d{3})*(?:\.\d{1,2})?)', line_lower)
                if not price_matches and i + 1 < len(lines):
                    next_line = lines[i+1].lower()
                    price_matches = re.findall(r'(\d+(?:,\d{3})*(?:\.\d{1,2})?)', next_line)
                for match in price_matches:
                    try:
                        price = float(match.replace(',', ''))
                        if price > 0:
                            total_values.append(price)
                    except ValueError:
                        continue
    if total_values:
        plausible_values = [c for c in total_values if c >= 10.0]
        total_amount = max(plausible_values) if plausible_values else max(total_values)
    else:
        all_numbers = re.findall(r'(\d+(?:,\d{3})*(?:\.\d{1,2})?)', text)
        if all_numbers:
            try:
                total_amount = float(all_numbers[-1].replace(',', ''))
            except ValueError:
                pass

    return company_name, total_amount

# Helper function to process uploaded files for text extraction
def process_file_for_extraction(filepath, filename):
    is_pdf = filename.lower().endswith(".pdf")
    all_extracted_text = []

    if is_pdf:
        doc = fitz.open(filepath)
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(dpi=300)
            img_bytes = pix.tobytes("png")
            img_np = np.frombuffer(img_bytes, dtype=np.uint8)
            img_cv2 = cv2.imdecode(img_np, cv2.IMREAD_COLOR)
            reader = get_ocr_reader()
            result = reader.readtext(img_cv2, detail=1)
            all_extracted_text.extend(result)
        doc.close()
    else:
        img_cv2 = cv2.imread(filepath)
        if img_cv2 is None:
            raise ValueError("Invalid image path or unreadable file.")
        reader = get_ocr_reader()
        all_extracted_text = reader.readtext(img_cv2, detail=1)

    all_extracted_text.sort(key=lambda x: x[0][0][1])
    extracted_text_string = ""
    current_line_y = -1
    line_threshold = 10
    for (bbox, text, prob) in all_extracted_text:
        x_min, y_min = bbox[0]
        if current_line_y == -1 or abs(y_min - current_line_y) > line_threshold:
            if extracted_text_string:
                extracted_text_string += "\n"
            extracted_text_string += text
            current_line_y = y_min
        else:
            extracted_text_string += " " + text

    date_val = parse_date_from_text(extracted_text_string)
    company_name, total_amount = extract_summary_from_text(extracted_text_string)
    return {"date": date_val, "company_name": company_name, "total_amount": total_amount, "raw_text": extracted_text_string}


def create_app():
    app = Flask(__name__)
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    
    # MongoDB Configuration with explicit write concern for data persistence
    # Write concern ensures writes are acknowledged and committed to disk
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/sem5")
    # Add write concern parameters to URI if not already present
    if "w=" not in mongo_uri:
        separator = "&" if "?" in mongo_uri else "?"
        mongo_uri = f"{mongo_uri}{separator}w=1&journal=true&wtimeoutMS=5000"
    app.config["MONGO_URI"] = mongo_uri
    app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    
    # Session Configuration - Use server-side MongoDB sessions for proper isolation
    # This allows different users to login in different tabs without conflicts
    # Each tab gets a unique session ID stored in MongoDB
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)  # 24 hour session timeout
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production with HTTPS
    app.config['SESSION_COOKIE_NAME'] = 'housewise_session'
    app.config['SESSION_COOKIE_DOMAIN'] = None
    
    # Note: Flask's default cookie-based sessions are shared across tabs in the same browser
    # For true session isolation, each tab would need a unique session ID
    # This is a limitation of cookie-based sessions. For production, consider:
    # 1. Using different browsers/incognito mode for different users
    # 2. Implementing server-side sessions with unique IDs per tab
    # 3. Using Flask-Session with Redis/MongoDB backend
    
    # For now, we'll add a session ID to help with debugging
    import uuid
    
    # Initialize MongoDB with error handling
    try:
        mongo.init_app(app)
        mongo.db.command('ping')
        print("✅ MongoDB connected successfully!")
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")

    # Register custom template filter
    @app.template_filter()
    def currency_format(value):
        try:
            return "₹{:,.2f}".format(float(value))
        except:
            return value

    def get_gmail_service():
        creds = None
        if os.path.exists(TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, GMAIL_SEND_SCOPES)
        # If no valid creds, run OAuth flow
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(CREDS_FILE):
                    raise RuntimeError("❌ Gmail API credentials not found. Place credentials.json in project folder.")
                flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, GMAIL_SEND_SCOPES)
                creds = flow.run_local_server(port=0)
            with open(TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())
        service = build('gmail', 'v1', credentials=creds)
        return service
    
    # Helper: format Indian currency
    def format_indian_currency(amount):
        try:
            amount = float(amount)
        except Exception:
            return amount
        amount_str = "{:.2f}".format(amount)
        main_part, decimal_part = amount_str.split('.')
        if len(main_part) > 3:
            last_three = main_part[-3:]
            remaining = main_part[:-3]
            formatted_remaining = ""
            for i in range(len(remaining)):
                formatted_remaining += remaining[i]
                if (len(remaining) - i - 1) % 2 == 0 and i != len(remaining) - 1:
                    formatted_remaining += ","
            main_part = formatted_remaining + "," + last_three
        return "{}.{}".format(main_part, decimal_part)
    
    # Send email using Gmail API
    def send_email(subject, recipients, body):
        try:
            service = get_gmail_service()
            message = MIMEText(body)
            message['to'] = ", ".join(recipients)
            message['subject'] = subject
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            service.users().messages().send(userId='me', body={'raw': raw_message}).execute()
            return True, None
        except Exception as e:
            print(f"Failed to send email to {recipients}: {e}")
            return False, str(e)
    
    def send_due_bill_notifications():
        """Check for bills due today and send email reminders automatically."""
        with app.app_context():
            today = datetime.now(timezone.utc).date().isoformat()
            print(f"🔄 Checking due bills for {today}")

            try:
                bills_due = list(mongo.db.bills.find({"due_date": today}))
            except Exception as e:
                app.logger.error(f"❌ Could not query bills: {e}")
                bills_due = []

            if not bills_due:
                print("ℹ️ No bills due today.")
                return

            for bill in bills_due:
                amount_formatted = format_indian_currency(bill.get('amount', 0))
                recipients = []

                # Determine recipients
                if isinstance(bill.get('recipients'), list) and bill.get('recipients'):
                    recipients = [r.strip() for r in bill['recipients'] if isinstance(r, str) and r.strip()]
                elif bill.get('user_email'):
                    recipients = [bill['user_email']]
                elif bill.get('user_id'):
                    try:
                        uid_obj = ObjectId(bill['user_id']) if isinstance(bill['user_id'], str) else bill['user_id']
                        user = mongo.db.users.find_one({'_id': uid_obj})
                        if user and user.get('email') and user.get('email_notifications', True):
                            recipients = [user['email']]
                    except Exception as e:
                        app.logger.warning(f"⚠️ Could not resolve user for bill {bill.get('_id')}: {e}")
                elif bill.get('broadcast'):
                    try:
                        users_cursor = mongo.db.users.find({
                            'email': {'$exists': True},
                            '$or': [{'email_notifications': {'$exists': False}}, {'email_notifications': True}]
                        })
                        recipients = [u['email'] for u in users_cursor if u.get('email')]
                    except Exception as e:
                        app.logger.warning(f"⚠️ Broadcast recipient fetch failed: {e}")

                recipients = list(dict.fromkeys([r for r in recipients if r]))
                if not recipients:
                    app.logger.info(f"ℹ️ No recipients for bill {bill.get('name','Unnamed Bill')}")
                    continue

                # Build email body
                body = f"Reminder: Your {bill.get('name','bill')} of ₹{amount_formatted} is due today ({today})."

                # Send email
                sent, err = send_email("📅 Bill Due Reminder", recipients, body)
                if sent:
                    app.logger.info(f"✅ Bill reminder sent to {recipients} for {bill.get('name','Unknown Bill')}")
                    print(f"✅ Email sent to {recipients}")
                else:
                    app.logger.error(f"❌ Failed sending bill reminder to {recipients}: {err}")

                # Handle monthly repeat
                if bill.get('repeat_monthly'):
                    try:
                        current_due_date = datetime.fromisoformat(bill['due_date'])
                        next_month = (current_due_date + timedelta(days=30)).date()
                        mongo.db.bills.update_one({'_id': bill['_id']}, {'$set': {'due_date': next_month.isoformat()}})
                        app.logger.info(f"🔁 Bill {bill.get('name','Unnamed Bill')} rescheduled for {next_month}")
                    except Exception as e:
                        app.logger.warning(f"⚠️ Could not reschedule monthly bill {bill.get('_id')}: {e}")


    def send_due_medical_notifications():
        """Check for medical reminders due today and send emails automatically."""
        with app.app_context():
            today = datetime.now(timezone.utc).date().isoformat()
            print(f"🔄 Checking medical reminders for {today}")

            try:
                meds_due = list(mongo.db.medical.find({"date": today}))
            except Exception as e:
                app.logger.error(f"❌ Could not query medical reminders: {e}")
                meds_due = []

            if not meds_due:
                print("ℹ️ No medical reminders for today.")
                return

            for m in meds_due:
                recipients = []

                if isinstance(m.get('recipients'), list) and m.get('recipients'):
                    recipients = [r.strip() for r in m['recipients'] if isinstance(r, str) and r.strip()]
                elif m.get('user_email'):
                    recipients = [m['user_email']]
                elif m.get('user_id'):
                    try:
                        uid_obj = ObjectId(m['user_id']) if isinstance(m['user_id'], str) else m['user_id']
                        user = mongo.db.users.find_one({'_id': uid_obj})
                        if user and user.get('email') and user.get('email_notifications', True):
                            recipients = [user['email']]
                    except Exception as e:
                        app.logger.warning(f"⚠️ Could not resolve user for reminder {m.get('_id')}: {e}")
                elif m.get('broadcast'):
                    try:
                        users_cursor = mongo.db.users.find({
                            'email': {'$exists': True},
                            '$or': [{'email_notifications': {'$exists': False}}, {'email_notifications': True}]
                        })
                        recipients = [u['email'] for u in users_cursor if u.get('email')]
                    except Exception as e:
                        app.logger.warning(f"⚠️ Broadcast recipient fetch failed (medical): {e}")

                recipients = list(dict.fromkeys([r for r in recipients if r]))
                if not recipients:
                    app.logger.info(f"ℹ️ No recipients for medical reminder {m.get('title','Unknown')}")
                    continue

                # Build email body
                body = f"Medical Reminder: {m.get('title','Appointment')} scheduled for today ({today})."

                # Send email
                sent, err = send_email("💊 Medical Reminder", recipients, body)
                if sent:
                    app.logger.info(f"✅ Medical reminder sent to {recipients} for {m.get('title','Unknown')}")
                    print(f"✅ Medical reminder email sent to {recipients}")
                else:
                    app.logger.error(f"❌ Failed sending medical reminder to {recipients}: {err}")

                # Handle monthly repeat
                if m.get('repeat_monthly'):
                    try:
                        current_date = datetime.fromisoformat(m['date'])
                        next_month = (current_date + timedelta(days=30)).date()
                        mongo.db.medical.update_one({'_id': m['_id']}, {'$set': {'date': next_month.isoformat()}})
                        app.logger.info(f"🔁 Medical reminder {m.get('title','Unnamed Reminder')} rescheduled for {next_month}")
                    except Exception as e:
                        app.logger.warning(f"⚠️ Could not reschedule monthly medical reminder {m.get('_id')}: {e}")


    # ---------------- AUTOMATED DAILY SCHEDULER ----------------
    def auto_post_recurring_income():
        """Automatically post recurring income entries for the current month"""
        with app.app_context():
            today = datetime.now(timezone.utc).date()
            this_month_key = today.strftime('%Y-%m')
            
            try:
                # Get all active recurring income definitions
                all_recurring = list(mongo.db.incomes_recurring.find({"active": True}))
                posted_count = 0
                
                for rec in all_recurring:
                    user_id = rec.get('user_id')
                    if not user_id:
                        continue
                    
                    # Determine expected date this month
                    if rec.get("frequency") == "monthly":
                        dom = rec.get("day_of_month") or 1
                        try:
                            expected_date = date(today.year, today.month, min(dom, 28))
                        except Exception:
                            expected_date = today.replace(day=1)
                    else:
                        expected_date = today
                    
                    post_date_str = expected_date.strftime('%Y-%m-%d')
                    
                    # Check if already posted this month
                    already_posted = mongo.db.incomes.count_documents({
                        "user_id": user_id,
                        "source": rec.get("source"),
                        "$expr": {"$eq": [{"$substr": ["$date", 0, 7]}, this_month_key]},
                        "amount": float(rec.get("amount", 0)),
                        "recurring_id": rec.get("_id")
                    }) > 0
                    
                    # Only post if not already posted and it's past the day of month
                    if not already_posted and today >= expected_date:
                        try:
                            mongo.db.incomes.insert_one({
                                "user_id": user_id,
                                "source": rec.get("source"),
                                "amount": float(rec.get("amount", 0)),
                                "date": post_date_str,
                                "created_at": datetime.utcnow(),
                                "recurring_id": rec.get("_id")
                            })
                            posted_count += 1
                            app.logger.info(f"✅ Auto-posted recurring income: {rec.get('source')} - ₹{rec.get('amount')} for user {user_id}")
                        except Exception as e:
                            app.logger.error(f"❌ Error auto-posting recurring income {rec.get('_id')}: {e}")
                
                if posted_count > 0:
                    print(f"✅ Auto-posted {posted_count} recurring income entries for {this_month_key}")
                else:
                    print(f"ℹ️ No new recurring income to post for {this_month_key}")
                    
            except Exception as e:
                app.logger.error(f"❌ Error in auto_post_recurring_income: {e}")
                print(f"❌ Error auto-posting recurring income: {e}")

    try:
        scheduler = BackgroundScheduler()

        # Run both jobs once daily at 9 AM server time
        scheduler.add_job(send_due_bill_notifications, 'cron', hour=9, minute=0)
        scheduler.add_job(send_due_medical_notifications, 'cron', hour=9, minute=5)
        # Auto-post recurring income daily at 9:10 AM (checks if it's the right day of month)
        scheduler.add_job(auto_post_recurring_income, 'cron', hour=9, minute=10)

        scheduler.start()
        atexit.register(lambda: scheduler.shutdown(wait=False))
        app.logger.info("📅 Scheduler started successfully. Will run daily at 9:00 AM.")
        print("✅ Scheduler running: Bills @ 9:00 AM, Medical @ 9:05 AM, Recurring Income @ 9:10 AM daily.")

    except Exception as e:
        app.logger.error(f"❌ Could not start scheduler: {e}")
        print(f"❌ Scheduler failed: {e}")

    # --- SESSION MANAGEMENT HOOK ---
    # This helps maintain session integrity across tabs
    @app.before_request
    def check_session_integrity():
        """Verify and restore session from MongoDB if cookie was overwritten"""
        # Skip session check for login, logout, and static files
        if request.endpoint in ['login', 'logout', 'signup', 'static']:
            return
        
        try:
            if 'session_id' in session and mongo.db is not None:
                session_doc = mongo.db.user_sessions.find_one({'session_id': session['session_id']})
                if session_doc:
                    # Restore user data from MongoDB if session cookie was overwritten
                    if session.get('user_id') != session_doc.get('user_id'):
                        session['user_id'] = session_doc.get('user_id')
                        session['user_email'] = session_doc.get('user_email')
                        session['user_name'] = session_doc.get('user_name')
                    # Check if session expired
                    expires_at = session_doc.get('expires_at')
                    if expires_at and isinstance(expires_at, datetime) and expires_at < datetime.utcnow():
                        mongo.db.user_sessions.delete_one({'session_id': session['session_id']})
                        session.clear()
        except Exception as e:
            # Don't break the app if session check fails
            app.logger.warning(f"Session integrity check failed: {e}")
            pass

    # --- ROUTES ---

    @app.route("/")
    def home():
        return render_template('index.html')

    @app.route('/dashboard')
    @login_required
    def dashboard():
        user_id = session.get('user_id')
        if not user_id:
            flash("User not logged in.", "error")
            return redirect(url_for('login'))

        # --- Month Selection (Dropdown support) ---
        today = datetime.today()
        selected_month = request.args.get("month")

        if selected_month:
            try:
                month_date = datetime.strptime(selected_month, "%Y-%m")
            except ValueError:
                month_date = today
        else:
            month_date = today

        month_str = month_date.strftime("%Y-%m")

        # Convert user_id to ObjectId for queries
        try:
            user_id_obj = ObjectId(user_id) if not isinstance(user_id, ObjectId) else user_id
        except:
            user_id_obj = user_id

        # --- Fetch data for selected month ---
        expenses_cursor = mongo.db.purchases.find({
            "user_id": user_id_obj,
            "date": {"$regex": f"^{month_str}"}
        })
        total_expenses = sum(float(item.get("amount", 0)) for item in expenses_cursor)
            
        incomes_cursor = mongo.db.incomes.find({
            "user_id": user_id_obj,
            "date": {"$regex": f"^{month_str}"}
        })
        total_income = sum(float(item.get("amount", 0)) for item in incomes_cursor)

        total_balance = total_income - total_expenses

        # --- Savings / Overspending message ---
        if total_income > total_expenses:
            message = f"You saved ₹{total_balance:,.2f} in {month_date.strftime('%B %Y')} 🎉"
            message_type = "success"
        elif total_expenses > total_income:
            message = f"You overspent ₹{abs(total_balance):,.2f} in {month_date.strftime('%B %Y')} ⚠️"
            message_type = "danger"
        else:
            message = f"You broke even in {month_date.strftime('%B %Y')} — nice balance!"
            message_type = "info"

        # --- Other summaries ---
        segments = spending_segments(user_id)
        breakdown = expense_breakdown_by_subcategory(user_id)
        cashflow_timeseries = monthly_cashflow(user_id)
        segments_30 = last_30_days_segments(user_id)
        breakdown_30 = last_30_days_breakdown(user_id)
        regular_count_30 = regular_spending_count(user_id, last_n_days=30)
        top_3 = top_3_categories(user_id, 30)

        # --- Cashflow banner ---
        if total_balance > 0:
            cashflow_status_data = {
                "status": "positive",
                "message": f"You saved ₹{total_balance:,.0f} this month",
                "color": "#10B981",
                "icon": "✅",
                "balance": total_balance
            }
        elif total_balance == 0:
            cashflow_status_data = {
                "status": "neutral",
                "message": "You broke even this month",
                "color": "#F59E0B",
                "icon": "⚖️",
                "balance": total_balance
            }
        else:
            cashflow_status_data = {
                "status": "negative",
                "message": f"You overspent ₹{abs(total_balance):,.0f} this month",
                "color": "#EF4444",
                "icon": "⚠️",
                "balance": total_balance
            }

        # --- Recent transactions ---
        recent_expenses = list(
            mongo.db.purchases.find({
                "user_id": user_id_obj,
                "date": {"$regex": f"^{month_str}"}
            }).sort([("date", -1), ("_id", -1)]).limit(5)
        )
            
        recent_incomes = list(
            mongo.db.incomes.find({
                "user_id": user_id_obj,
                "date": {"$regex": f"^{month_str}"}
            }).sort([("date", -1), ("_id", -1)]).limit(5)
        )

        all_recent_transactions = sorted(
            recent_expenses + recent_incomes,
            key=lambda x: datetime.strptime(x.get("date", "1970-01-01"), "%Y-%m-%d"),
            reverse=True
        )

        # Serialize ObjectIds for JSON
        for t in all_recent_transactions:
            if '_id' in t:
                t['id'] = str(t.pop('_id'))
            else:
                t['id'] = None
            # Convert any remaining ObjectIds to strings
            if 'user_id' in t and isinstance(t['user_id'], ObjectId):
                t['user_id'] = str(t['user_id'])

        # Fetch upcoming bills and medical reminders for this user (next 30 days, including overdue)
        upcoming_bills = []
        upcoming_medical = []
        try:
            today_date = datetime.now().date()
            in_30 = (today_date + timedelta(days=30)).isoformat()
            today_iso = today_date.isoformat()
            # Also include overdue items (up to 7 days past due)
            past_7_days = (today_date - timedelta(days=7)).isoformat()
            
            if user_id_obj:
                # Fetch bills due in next 30 days or overdue (within last 7 days)
                upcoming_bills = list(mongo.db.bills.find({
                    'user_id': user_id_obj,
                    '$or': [
                        {'due_date': {'$gte': today_iso, '$lte': in_30}},
                        {'due_date': {'$gte': past_7_days, '$lt': today_iso}}  # Overdue but not too old
                    ]
                }).sort('due_date', 1).limit(10))
                
                # Fetch medical reminders due in next 30 days or overdue (within last 7 days)
                upcoming_medical = list(mongo.db.medical.find({
                    'user_id': user_id_obj,
                    '$or': [
                        {'date': {'$gte': today_iso, '$lte': in_30}},
                        {'date': {'$gte': past_7_days, '$lt': today_iso}}  # Overdue but not too old
                    ]
                }).sort('date', 1).limit(10))
                
                # Serialize ObjectIds and calculate days until due
                today_date = datetime.now().date()
                urgent_bills = []
                urgent_medical = []
                
                for bill in upcoming_bills:
                    if '_id' in bill:
                        bill['id'] = str(bill.pop('_id'))
                    if 'user_id' in bill and isinstance(bill['user_id'], ObjectId):
                        bill['user_id'] = str(bill['user_id'])
                    # Calculate days until due
                    if bill.get('due_date'):
                        try:
                            due_date_str = bill['due_date'].split('T')[0] if 'T' in bill['due_date'] else bill['due_date']
                            due_date_obj = datetime.strptime(due_date_str, '%Y-%m-%d').date()
                            days_diff = (due_date_obj - today_date).days
                            # Ensure days_diff is a valid integer, not 999 or None
                            bill['days_until_due'] = days_diff if isinstance(days_diff, int) else None
                            # Only include bills due within 3 days or overdue
                            if bill['days_until_due'] is not None and bill['days_until_due'] <= 3:
                                urgent_bills.append(bill)
                        except Exception as e:
                            app.logger.warning(f"Error calculating days until due for bill {bill.get('_id')}: {e}")
                            bill['days_until_due'] = None
                    else:
                        bill['days_until_due'] = None
                
                for med in upcoming_medical:
                    if '_id' in med:
                        med['id'] = str(med.pop('_id'))
                    if 'user_id' in med and isinstance(med['user_id'], ObjectId):
                        med['user_id'] = str(med['user_id'])
                    # Calculate days until due
                    if med.get('date'):
                        try:
                            med_date_str = med['date'].split('T')[0] if 'T' in med['date'] else med['date']
                            med_date_obj = datetime.strptime(med_date_str, '%Y-%m-%d').date()
                            days_diff = (med_date_obj - today_date).days
                            # Ensure days_diff is a valid integer, not 999 or None
                            med['days_until_due'] = days_diff if isinstance(days_diff, int) else None
                            # Only include medical reminders due within 3 days or overdue
                            if med['days_until_due'] is not None and med['days_until_due'] <= 3:
                                urgent_medical.append(med)
                        except Exception as e:
                            app.logger.warning(f"Error calculating days until due for medical {med.get('_id')}: {e}")
                            med['days_until_due'] = None
                    else:
                        med['days_until_due'] = None
                
                # Update upcoming_bills and upcoming_medical to only urgent ones for notifications
                urgent_reminders = {
                    'bills': urgent_bills,
                    'medical': urgent_medical
                }
        except Exception as e:
            app.logger.error(f"Error fetching reminders: {e}")
            upcoming_bills = []
            upcoming_medical = []
            urgent_reminders = {'bills': [], 'medical': []}

        # --- Budget Settings ---
        settings = mongo.db.settings.find_one({"user_id": user_id}) or {}
        limits = settings.get("limits", {})
        monthly_limit = float(limits.get("monthly_budget", 0))
        category_limits = {k: v for k, v in limits.items() if k != "monthly_budget"}

        alerts = []

        # Monthly budget alert
        if monthly_limit > 0 and total_expenses > monthly_limit:
            exceeded = total_expenses - monthly_limit
            alerts.append({
                "type": "monthly",
                "message": f"You've exceeded your monthly budget by ₹{exceeded:,.0f}."
            })

        # Category alerts
        def _norm_key(s):
            return re.sub(r"[^a-z]", "", (s or "").lower())

        norm_category_limits = {}
        for k, v in category_limits.items():
            if k == "monthly_budget":
                continue
            norm_category_limits[_norm_key(k)] = float(v) if v is not None else 0.0

        category_spent_norm = {}
        for item in mongo.db.purchases.find({
            "user_id": user_id_obj,
            "date": {"$regex": f"^{month_str}"}
        }):
            cat = item.get("category", "Uncategorized")
            nkey = _norm_key(cat)
            category_spent_norm[nkey] = category_spent_norm.get(nkey, 0.0) + float(item.get("amount", 0))

        for nkey, limit in norm_category_limits.items():
            limit_value = float(limit)
            spent = float(category_spent_norm.get(nkey, 0.0))

            if limit_value > 0 and spent >= 0.9 * limit_value and spent <= limit_value:
                alerts.append({
                    "type": "category",
                    "category": nkey,
                    "message": f"You're close to your {nkey} budget (₹{spent:,.0f}/₹{limit_value:,.0f})."
                })

            if limit_value > 0 and spent > limit_value:
                exceeded = spent - limit_value
                alerts.append({
                    "type": "category",
                    "category": nkey,
                    "message": f"You've overspent ₹{exceeded:,.0f} in {nkey}."
                })

        unique_alerts = []
        seen = set()
        for a in alerts:
            key = a.get("category") or "monthly"
            if key not in seen:
                unique_alerts.append(a)
                seen.add(key)

        # --- Month List for Dropdown ---
        month_options = [
            {"value": f"{today.year}-{i:02d}", "label": datetime(today.year, i, 1).strftime("%B")}
            for i in range(1, 13)
        ]

        # --- ML Features (Predictions & Suggestions) ---
        ml_predictions = []
        ml_suggestions = []
        ml_item_suggestions = []
        ml_spending_peaks = []
        try:
            from ml_features.ml_service import MLService
            ml_service = MLService()
            
            # Get predictions (next 7 days) with incremental learning
            pred_result = ml_service.get_expense_predictions(user_id, days_ahead=7, incremental=True)
            if pred_result.get('predictions'):
                ml_predictions = pred_result['predictions'][:5]  # Top 5 for dashboard
            
            # Get spending peaks and category warnings (iPhone-style notifications)
            ml_spending_peaks = pred_result.get('peaks', [])[:3]  # Top 3 peaks for dashboard
            ml_category_warnings = pred_result.get('category_warnings', [])[:5]  # Top 5 category warnings
            
            # Get buying suggestions
            sugg_result = ml_service.get_buying_suggestions(user_id, top_n=5)
            if sugg_result.get('item_suggestions'):
                ml_item_suggestions = sugg_result['item_suggestions'][:5]  # Top 5 for dashboard
        except Exception as e:
            # ML features are optional, don't break dashboard if they fail
            app.logger.warning(f"ML features not available on dashboard: {e}")
            ml_predictions = []
            ml_item_suggestions = []
            ml_spending_peaks = []

        # --- Render ---

        return render_template(
            "dashboard.html",
            total_balance=total_balance,
            total_income=total_income,
            total_expenses=total_expenses,
            segments=segments,
            breakdown=breakdown,
            cashflow=cashflow_timeseries,
            segments_30=segments_30,
            breakdown_30=breakdown_30,
            regular_count_30=regular_count_30,
            top_3=top_3,
            cashflow_status=cashflow_status_data,
            recent_expenses=recent_expenses,
            recent_incomes=recent_incomes,
            all_recent_transactions=all_recent_transactions,
            upcoming_bills=upcoming_bills,
            upcoming_medical=upcoming_medical,
            urgent_reminders=urgent_reminders,
            month_name=month_date.strftime("%B %Y"),
            selected_month=month_str,
            month_options=month_options,
            message=message,
            message_type=message_type,
            monthly_limit=monthly_limit,
            category_limits=category_limits,
            alerts=unique_alerts,
            ml_predictions=ml_predictions,
            ml_item_suggestions=ml_item_suggestions,
            ml_spending_peaks=ml_spending_peaks,
            ml_category_warnings=ml_category_warnings
        )


    @app.route('/signup', methods=['GET', 'POST'])
    def signup():
        if request.method == "POST":
            fullname = request.form.get("fullname")
            email = request.form.get("email").lower()
            password = request.form.get("password")

            if not (fullname and email and password):
                flash("All fields are required!", "error")
                return redirect(url_for("signup"))

            try:
                existing_user = mongo.db.users.find_one({"email": email})
                if existing_user:
                    flash("Email already registered! Please login instead.", "error")
                    return redirect(url_for("login"))

                mongo.db.users.insert_one({
                    "fullname": fullname,
                    "email": email,
                    "password_hash": generate_password_hash(password),
                    "created_at": datetime.utcnow()
                })

                flash("Signup successful! Please login.", "success")
                return redirect(url_for("login"))
                
            except Exception as e:
                flash(f"Database error: {str(e)}", "error")
                return redirect(url_for("signup"))

        return render_template("signup.html")

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == "POST":
            # Normalize inputs to avoid whitespace/case issues
            email = (request.form.get("email") or "").strip().lower()
            password = (request.form.get("password") or "").strip()

            try:
                # Case-insensitive match on email to tolerate unexpected casing in stored records
                user = mongo.db.users.find_one({
                    "email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}
                })
                if user and check_password_hash(user["password_hash"], password):
                    # Make session permanent to use the configured timeout
                    session.permanent = True
                    # Generate a unique session ID for this login to help with tab isolation
                    # Note: This doesn't fully solve the cookie-sharing issue, but helps track sessions
                    session['session_id'] = str(uuid.uuid4())
                    session['user_id'] = str(user['_id'])
                    session['user_email'] = user['email']
                    session['user_name'] = user['fullname']
                    session['login_time'] = datetime.utcnow().isoformat()
                    # Store session in MongoDB for server-side tracking
                    if mongo.db is not None:
                        mongo.db.user_sessions.update_one(
                            {'session_id': session['session_id']},
                            {'$set': {
                                'user_id': str(user['_id']),
                                'user_email': user['email'],
                                'user_name': user['fullname'],
                                'login_time': datetime.utcnow(),
                                'expires_at': datetime.utcnow() + app.config['PERMANENT_SESSION_LIFETIME']
                            }},
                            upsert=True
                        )
                    flash("Login successful!", "success")
                    return redirect(url_for("dashboard"))
                else:
                    flash("Invalid credentials!", "error")
            except Exception as e:
                flash(f"Database error: {str(e)}", "error")

        return render_template("login.html")

    @app.route('/logout')
    def logout():
        # Clear server-side session tracking
        if mongo.db is not None and 'session_id' in session:
            mongo.db.user_sessions.delete_one({'session_id': session['session_id']})
        session.clear()
        flash("You have been logged out.", "success")
        return redirect(url_for("login"))

    @app.route('/bills', methods=['GET', 'POST'])
    @login_required
    def bills():
        user_id = session.get('user_id')
        if not user_id:
            flash("User not logged in.", "error")
            return redirect(url_for('login'))
        
        try:
            user_id_obj = ObjectId(user_id) if not isinstance(user_id, ObjectId) else user_id
        except:
            user_id_obj = user_id
        
        if request.method == 'POST':
            name = request.form.get('name')
            amount = request.form.get('amount')
            due_date = request.form.get('due_date')
            recipients_raw = request.form.get('recipients') or ''
            repeat_monthly = request.form.get('repeat_monthly') == 'on'
            broadcast = request.form.get('broadcast') == 'on'

            try:
                amount_val = float(amount) if amount else 0.0
            except Exception:
                amount_val = 0.0

            recipients = [r.strip() for r in recipients_raw.split(',') if r.strip()]

            doc = {
                'name': name,
                'amount': amount_val,
                'due_date': due_date,
                'user_id': user_id_obj,
                'recipients': recipients,
                'repeat_monthly': repeat_monthly,
                'broadcast': broadcast,
                'created_at': datetime.utcnow()
            }
            mongo.db.bills.insert_one(doc)
            flash('Bill saved.', 'success')
            return redirect(url_for('bills'))

        upcoming = list(mongo.db.bills.find({'user_id': user_id_obj}).sort('due_date', 1))
        # convert ObjectId to string for template usage
        for b in upcoming:
            try:
                b['id'] = str(b.get('_id'))
            except Exception:
                b['id'] = None
        return render_template('bills.html', upcoming=upcoming)

    @app.route('/bills/delete/<string:bill_id>', methods=['POST'])
    @login_required
    def delete_bill(bill_id):
        user_id = session.get('user_id')
        if not user_id:
            flash("User not logged in.", "error")
            return redirect(url_for('login'))
        
        try:
            user_id_obj = ObjectId(user_id) if not isinstance(user_id, ObjectId) else user_id
            mongo.db.bills.delete_one({'_id': ObjectId(bill_id), 'user_id': user_id_obj})
            flash('Bill deleted.', 'success')
        except Exception as e:
            flash('Could not delete bill: ' + str(e), 'error')
        return redirect(url_for('bills'))

    @app.route('/send-now/bill/<string:bill_id>', methods=['POST'])
    @login_required
    def send_now_bill(bill_id):
        user_id = session.get('user_id')
        if not user_id:
            flash("User not logged in.", "error")
            return redirect(url_for('login'))
        
        try:
            user_id_obj = ObjectId(user_id) if not isinstance(user_id, ObjectId) else user_id
            bill = mongo.db.bills.find_one({'_id': ObjectId(bill_id)})
            if not bill:
                flash('Bill not found', 'error')
                return redirect(url_for('bills'))
            
            # Security check: ensure user owns this bill
            bill_user_id = bill.get('user_id')
            if bill_user_id:
                if isinstance(bill_user_id, ObjectId):
                    if bill_user_id != user_id_obj:
                        flash('Access denied', 'error')
                        return redirect(url_for('bills'))
                elif isinstance(bill_user_id, str):
                    if bill_user_id != user_id:
                        flash('Access denied', 'error')
                        return redirect(url_for('bills'))

            # Build recipients (reuse logic from scheduled job)
            recipients = []
            if isinstance(bill.get('recipients'), list) and bill.get('recipients'):
                recipients = [r for r in bill.get('recipients') if isinstance(r, str) and r]
            if not recipients and bill.get('user_email'):
                recipients = [bill['user_email']]
            if not recipients and bill.get('user_id'):
                user = mongo.db.users.find_one({'_id': bill['user_id']})
                if user and user.get('email') and user.get('email_notifications', True):
                    recipients = [user['email']]

            recipients = list(dict.fromkeys([r for r in recipients if isinstance(r, str) and r.strip()]))
            if not recipients:
                flash('No recipients found for this bill', 'error')
                return redirect(url_for('bills'))

            body = f"Reminder: Your {bill.get('name','bill')} of ₹{format_indian_currency(bill.get('amount',0))} is due {bill.get('due_date')}"
            sent, err = send_email('Bill Due Reminder', recipients, body)
            if sent:
                flash('Sent test email to: ' + ', '.join(recipients), 'success')
            else:
                show_err = os.getenv('DEBUG_MAIL_ERRORS', '0') in ('1', 'true', 'True')
                if show_err:
                    flash('Failed to send: ' + (err or 'unknown'), 'error')
                else:
                    flash('Failed to send test email. Check logs.', 'error')
        except Exception as e:
            app.logger.exception('Error in send_now_bill')
            flash('Unexpected error: ' + str(e), 'error')
        return redirect(url_for('bills'))

    @app.route('/medical', methods=['GET', 'POST'])
    @login_required
    def medical():
        user_id = session.get('user_id')
        if not user_id:
            flash("User not logged in.", "error")
            return redirect(url_for('login'))
        
        try:
            user_id_obj = ObjectId(user_id) if not isinstance(user_id, ObjectId) else user_id
        except:
            user_id_obj = user_id
        
        if request.method == 'POST':
            title = request.form.get('title')
            date_str = request.form.get('date')
            location = request.form.get('location')
            recipients_raw = request.form.get('recipients') or ''
            repeat_monthly = request.form.get('repeat_monthly') == 'on'
            broadcast = request.form.get('broadcast') == 'on'

            recipients = [r.strip() for r in recipients_raw.split(',') if r.strip()]

            doc = {
                'title': title,
                'date': date_str,
                'location': location,
                'user_id': user_id_obj,
                'recipients': recipients,
                'repeat_monthly': repeat_monthly,
                'broadcast': broadcast,
                'created_at': datetime.utcnow()
            }
            mongo.db.medical.insert_one(doc)
            flash('Medical reminder saved.', 'success')
            return redirect(url_for('medical'))

        upcoming = list(mongo.db.medical.find({'user_id': user_id_obj}).sort('date', 1))
        # convert ObjectId to string for template usage and calculate next_due_date
        today_date = datetime.now().date()
        for m in upcoming:
            try:
                m['id'] = str(m.get('_id'))
            except Exception:
                m['id'] = None
            # Calculate next_due_date for recurring reminders
            if m.get('repeat_monthly') and m.get('date'):
                try:
                    current_date = datetime.strptime(m['date'], '%Y-%m-%d').date()
                    if current_date < today_date:
                        # If date has passed, calculate next occurrence
                        next_date = current_date
                        while next_date < today_date:
                            next_date = (datetime.combine(next_date, datetime.min.time()) + timedelta(days=30)).date()
                        m['next_due_date'] = next_date.isoformat()
                    else:
                        # If date is in future, next is 30 days after current
                        next_date = (datetime.combine(current_date, datetime.min.time()) + timedelta(days=30)).date()
                        m['next_due_date'] = next_date.isoformat()
                except Exception as e:
                    app.logger.warning(f"Error calculating next_due_date for medical {m.get('_id')}: {e}")
                    m['next_due_date'] = None
            else:
                m['next_due_date'] = None
        return render_template('medical.html', upcoming=upcoming)

    @app.route('/medical/delete/<string:mid>', methods=['POST'])
    @login_required
    def delete_medical(mid):
        user_id = session.get('user_id')
        if not user_id:
            flash("User not logged in.", "error")
            return redirect(url_for('login'))
        
        try:
            user_id_obj = ObjectId(user_id) if not isinstance(user_id, ObjectId) else user_id
            mongo.db.medical.delete_one({'_id': ObjectId(mid), 'user_id': user_id_obj})
            flash('Medical reminder deleted.', 'success')
        except Exception as e:
            flash('Could not delete reminder: ' + str(e), 'error')
        return redirect(url_for('medical'))

    @app.route('/send-now/medical/<string:mid>', methods=['POST'])
    @login_required
    def send_now_medical(mid):
        user_id = session.get('user_id')
        if not user_id:
            flash("User not logged in.", "error")
            return redirect(url_for('login'))
        
        try:
            user_id_obj = ObjectId(user_id) if not isinstance(user_id, ObjectId) else user_id
            m = mongo.db.medical.find_one({'_id': ObjectId(mid)})
            if not m:
                flash('Reminder not found', 'error')
                return redirect(url_for('medical'))
            
            # Security check: ensure user owns this reminder
            med_user_id = m.get('user_id')
            if med_user_id:
                if isinstance(med_user_id, ObjectId):
                    if med_user_id != user_id_obj:
                        flash('Access denied', 'error')
                        return redirect(url_for('medical'))
                elif isinstance(med_user_id, str):
                    if med_user_id != user_id:
                        flash('Access denied', 'error')
                        return redirect(url_for('medical'))

            recipients = []
            if isinstance(m.get('recipients'), list) and m.get('recipients'):
                recipients = [r for r in m.get('recipients') if isinstance(r, str) and r]
            if not recipients and m.get('user_email'):
                recipients = [m['user_email']]
            if not recipients and m.get('user_id'):
                user = mongo.db.users.find_one({'_id': m['user_id']})
                if user and user.get('email') and user.get('email_notifications', True):
                    recipients = [user['email']]

            recipients = list(dict.fromkeys([r for r in recipients if isinstance(r, str) and r.strip()]))
            if not recipients:
                flash('No recipients found for this reminder', 'error')
                return redirect(url_for('medical'))

            body = f"Medical Reminder: {m.get('title','Appointment')} scheduled for {m.get('date')} at {m.get('location','')}."
            sent, err = send_email('Medical Reminder', recipients, body)
            if sent:
                flash('Sent test email to: ' + ', '.join(recipients), 'success')
            else:
                show_err = os.getenv('DEBUG_MAIL_ERRORS', '0') in ('1', 'true', 'True')
                if show_err:
                    flash('Failed to send: ' + (err or 'unknown'), 'error')
                else:
                    flash('Failed to send test email. Check logs.', 'error')
        except Exception as e:
            app.logger.exception('Error in send_now_medical')
            flash('Unexpected error: ' + str(e), 'error')
        return redirect(url_for('medical'))

    @app.route('/auth/google')
    def google_auth():
        return "Google login not implemented yet"

    @app.route('/forgotpw', methods=['GET', 'POST'])
    def forgotpw():
        if request.method == 'POST':
            flash("Password reset flow not implemented", "info")
            return redirect(url_for('login'))
        return render_template('forgotpw.html')

    @app.route('/test-notification', methods=['POST'])
    def test_notification():
        email = request.form.get('email') or session.get('user_email')
        if not email:
            flash('No email provided for test notification', 'error')
            return redirect(url_for('dashboard'))
        sent, err = send_email('HouseWise - Test Notification', [email], 'This is a test notification from HouseWise.')
        if sent:
            flash('Test notification sent to ' + email, 'success')
        else:
            # If developer enabled verbose mail errors, show the error message for debugging
            show_err = os.getenv('DEBUG_MAIL_ERRORS', '0') in ('1', 'true', 'True')
            if show_err and err:
                flash('Failed to send test notification: ' + err, 'error')
            else:
                flash('Failed to send test notification. Check mail settings.', 'error')
        return redirect(url_for('dashboard'))

    @app.route("/income", methods=["GET", "POST"])
    @login_required
    def income():
        user_id = session.get('user_id')

        if request.method == "POST":
            form_kind = request.form.get("form_kind", "one_time")
            
            # If form_kind not provided but we have source/amount/date, it's a one-time entry
            if not form_kind and request.form.get("source"):
                form_kind = "one_time"

            # One-time income entry
            if form_kind == "one_time":
                source = request.form.get("source")
                amount = request.form.get("amount")
                date_str = request.form.get("date")

                try:
                    amount = float(amount)
                    entry_date = parse(date_str).strftime('%Y-%m-%d')
                    income_entry = {
                        "user_id": ObjectId(user_id),
                        "source": source,
                        "amount": amount,
                        "date": entry_date,
                        "created_at": datetime.utcnow()
                    }
                    mongo.db.incomes.insert_one(income_entry)
                    flash("Income added successfully!", "success")
                except (ValueError, TypeError):
                    flash("Invalid input. Please enter a valid number for amount.", "error")
                except Exception as e:
                    flash(f"An error occurred: {e}", "error")

            # Add recurring income definition
            elif form_kind == "recurring":
                try:
                    source = request.form.get("rec_source")
                    amount = float(request.form.get("rec_amount"))
                    frequency = request.form.get("rec_frequency", "monthly")  # monthly/weekly
                    start_date = request.form.get("rec_start_date")  # YYYY-MM-DD
                    end_date = request.form.get("rec_end_date") or None
                    day_of_month = request.form.get("rec_day_of_month") or None
                    day_of_week = request.form.get("rec_day_of_week") or None  # 0-6 if weekly

                    doc = {
                        "user_id": ObjectId(user_id),
                        "source": source,
                        "amount": amount,
                        "frequency": frequency,
                        "start_date": start_date,
                        "end_date": end_date,
                        "day_of_month": int(day_of_month) if day_of_month else None,
                        "day_of_week": int(day_of_week) if day_of_week else None,
                        "active": True,
                        "created_at": datetime.utcnow()
                    }
                    mongo.db.incomes_recurring.insert_one(doc)
                    flash("Fixed income saved. It will be easy to add each period.", "success")
                except Exception as e:
                    flash(f"Could not save fixed income: {e}", "error")

            return redirect(url_for("income"))

        # Convert user_id to ObjectId for query
        try:
            user_id_obj = ObjectId(user_id) if not isinstance(user_id, ObjectId) else user_id
        except:
            flash("Invalid user session. Please log in again.", "error")
            return redirect(url_for('login'))
        
        income_data = list(mongo.db.incomes.find({"user_id": user_id_obj}).sort([
            ("date", -1),  # Newest date first
            ("created_at", -1),  # If same date, newest created_at first
            ("_id", -1)  # If same date and created_at, newest _id first
        ]))
        # Convert ObjectId to string for JSON serialization
        for entry in income_data:
            if '_id' in entry:
                entry['_id'] = str(entry['_id'])
            if 'user_id' in entry:
                entry['user_id'] = str(entry['user_id'])
        
        # Recurring definitions
        recurring_defs = list(mongo.db.incomes_recurring.find({"user_id": user_id_obj, "active": True}))

        # For each recurring def, determine if current period entry exists
        from datetime import date as _date
        today = _date.today()
        this_month_key = today.strftime('%Y-%m')
        posted_map = {}
        for rec in recurring_defs:
            rec_id = str(rec.get("_id"))
            rec["_id_str"] = rec_id
            # Determine expected date this month (monthly only for now)
            expected_date = None
            if rec.get("frequency") == "monthly":
                dom = rec.get("day_of_month") or 1
                try:
                    expected_date = _date(today.year, today.month, min(dom, 28)).strftime('%Y-%m-%d')
                except Exception:
                    expected_date = today.replace(day=1).strftime('%Y-%m-%d')
            # Check if an income with same source and amount exists this month
            exists = False
            if expected_date:
                mm = this_month_key
                exists = mongo.db.incomes.count_documents({
                    "user_id": user_id_obj,
                    "source": rec.get("source"),
                    "$expr": {"$eq": [{"$substr": ["$date", 0, 7]}, mm]},
                    "amount": float(rec.get("amount", 0))
                }) > 0
            posted_map[rec_id] = exists

        monthly_income = {}
        for income_entry in income_data:
            entry_month = datetime.strptime(income_entry['date'], '%Y-%m-%d').strftime('%Y-%m')
            monthly_income[entry_month] = monthly_income.get(entry_month, 0) + income_entry['amount']

        return render_template(
            "income.html",
            income_data=income_data,
            monthly_income=monthly_income,
            recurring_defs=recurring_defs,
            posted_map=posted_map
        )

    @app.route('/expense')
    @login_required
    def expense():
        purchases = []
        total_spent = 0.0
        
        user_id = session.get('user_id')
        if not user_id:
            flash("User not logged in.", "error")
            return redirect(url_for('login'))
        
        # Get pre-fill values from query parameters (for suggestions)
        prefilled_item = request.args.get('item', '')
        prefilled_category = request.args.get('category', '')
        prefilled_amount = request.args.get('amount', '')
        from_suggestion = request.args.get('from_suggestion', '')
        
        if mongo.db is not None:
            user_id_obj = ObjectId(user_id) if user_id else None
            # Sort by date (newest first), then by _id (newest first) for same dates
            # Also sort by created_at if it exists (for most recent additions)
            purchases = list(mongo.db.purchases.find({"user_id": user_id_obj}).sort([
                ("date", -1),  # Newest date first
                ("created_at", -1),  # If same date, newest created_at first
                ("_id", -1)  # If same date and created_at, newest _id first
            ]))
            total_spent = sum(p.get('amount', 0.0) for p in purchases)

        for p in purchases:
            p['id'] = str(p.pop('_id'))

        # Use user's monthly budget for alerting if configured
        settings_doc = {}
        if mongo.db is not None:
            user_id_obj = ObjectId(user_id) if user_id else None
            settings_doc = mongo.db.settings.find_one({"user_id": user_id_obj}) or {}
        limits = settings_doc.get("limits", {})
        monthly_budget_limit = float(limits.get("monthly_budget", 0))
        # Compute this month's spending only for alert visibility
        month_key = datetime.today().strftime('%Y-%m')
        month_spent = sum(
            float(p.get('amount', 0.0)) for p in purchases if str(p.get('date','')).startswith(month_key)
        )
        spending_limit_alert = monthly_budget_limit > 0 and month_spent > monthly_budget_limit
        
        # Add summary data
        segments = spending_segments(user_id)
        breakdown = expense_breakdown_by_subcategory(user_id)

        return render_template(
            "expense.html",
            purchases=purchases,
            alert=spending_limit_alert,
            total_spent=total_spent,
            segments=segments,
            breakdown=breakdown,
            date=date,
            prefilled_item=prefilled_item,
            prefilled_category=prefilled_category,
            prefilled_amount=prefilled_amount,
            from_suggestion=from_suggestion
        )

    @app.route("/delete_purchase/<purchase_id>", methods=["POST"])
    @login_required
    def delete_purchase(purchase_id):
        user_id = session.get('user_id')
        if mongo.db is not None:
            user_id_obj = ObjectId(user_id) if user_id else None
            result = mongo.db.purchases.delete_one({"_id": ObjectId(purchase_id), "user_id": user_id_obj})
            if result.deleted_count > 0:
                flash("Purchase deleted successfully!", "success")
            else:
                flash("Purchase not found or you don't have permission to delete it.", "error")
        else:
            flash("Could not connect to database.", "error")
        return redirect(url_for("expense"))

    @app.route("/delete-income/<income_id>", methods=["POST"])
    @login_required
    def delete_income(income_id):
        user_id = session.get('user_id')
        if mongo.db is not None:
            result = mongo.db.incomes.delete_one({"_id": ObjectId(income_id), "user_id": ObjectId(user_id)})
            if result.deleted_count > 0:
                flash("Income source deleted successfully!", "success")
            else:
                flash("Income source not found or you don't have permission to delete it.", "error")
        else:
            flash("Could not connect to database.", "error")
        return redirect(url_for("income"))

    @app.route("/edit_purchase/<purchase_id>", methods=["POST"])
    @login_required
    def edit_purchase(purchase_id):
        user_id = session.get('user_id')
        try:
            item = request.form['item']
            amount = float(request.form['amount'])
            date_str = request.form['date']
            category = request.form['category']

            if mongo.db is not None:
                user_id_obj = ObjectId(user_id) if user_id else None
                result = mongo.db.purchases.update_one(
                    {"_id": ObjectId(purchase_id), "user_id": user_id_obj},
                    {"$set": {"item": item, "amount": amount, "date": date_str, "category": category}}
                )
                if result.matched_count > 0:
                    flash("Purchase updated successfully!", "success")
                else:
                    flash("Purchase not found or you don't have permission to edit it.", "error")
            else:
                flash("Could not connect to database.", "error")
        except (ValueError, KeyError) as e:
            flash(f"Error updating purchase: {e}", "error")
        except Exception as e:
            flash(f"Error updating purchase: {e}", "error")

        return redirect(url_for("expense"))
    
    @app.route('/income/recurring/post/<rec_id>', methods=['POST'])
    @login_required
    def post_recurring_income(rec_id):
        user_id = session.get('user_id')
        rec = mongo.db.incomes_recurring.find_one({"_id": ObjectId(rec_id), "user_id": ObjectId(user_id), "active": True})
        if not rec:
            flash("Fixed income not found.", "error")
            return redirect(url_for('income'))
        from datetime import date as _date
        today = _date.today()
        # Determine date to post (monthly default)
        if rec.get("frequency") == "monthly":
            dom = rec.get("day_of_month") or 1
            try:
                post_date = _date(today.year, today.month, min(dom, 28)).strftime('%Y-%m-%d')
            except Exception:
                post_date = today.replace(day=1).strftime('%Y-%m-%d')
        else:
            post_date = today.strftime('%Y-%m-%d')

        mongo.db.incomes.insert_one({
            "user_id": ObjectId(user_id),
            "source": rec.get("source"),
            "amount": float(rec.get("amount", 0)),
            "date": post_date,
            "created_at": datetime.utcnow(),
            "recurring_id": rec.get("_id")
        })
        flash("This month's fixed income added.", "success")
        return redirect(url_for('income'))


    @app.route('/income/recurring/toggle/<rec_id>', methods=['POST'])
    @login_required
    def toggle_recurring_income(rec_id):
        user_id = session.get('user_id')
        rec = mongo.db.incomes_recurring.find_one({"_id": ObjectId(rec_id), "user_id": ObjectId(user_id)})
        if not rec:
            flash("Fixed income not found.", "error")
            return redirect(url_for('income'))
        new_active = not bool(rec.get("active", True))
        mongo.db.incomes_recurring.update_one({"_id": ObjectId(rec_id)}, {"$set": {"active": new_active}})
        flash(("Re-enabled" if new_active else "Paused") + " fixed income.", "success")
        return redirect(url_for('income'))


    @app.route("/upload-invoice", methods=["GET", "POST"])
    @login_required
    def upload_invoice():
        user_id = session.get('user_id')
        if request.method == "POST":
            # Check for file upload first
            uploaded_file = request.files.get("invoice_file")
            if uploaded_file and uploaded_file.filename != '':
                if allowed_file(uploaded_file.filename):
                    filename = secure_filename(uploaded_file.filename)
                    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                    uploaded_file.save(filepath)

                    try:
                        summary = process_file_for_extraction(filepath, filename)
                        
                        if mongo.db is not None:
                            user_id_obj = ObjectId(user_id) if user_id else None
                            # Auto-detect category from company name using rule-based matching
                            detected_category = detect_category_from_item(summary["company_name"], item_type='expense', amount=summary.get("total_amount", 0.0))
                            category = detected_category if detected_category else "Receipt"
                            
                            mongo.db.purchases.insert_one({
                                "user_id": user_id_obj,
                                "item": summary["company_name"],
                                "amount": summary["total_amount"],
                                "date": summary["date"],
                                "category": category,
                                "created_at": datetime.now(timezone.utc)
                            })
                            flash(f"Invoice from {summary['company_name']} uploaded with total ₹{summary['total_amount']}", "success")
                        else:
                            flash("Could not connect to database.", "error")
                    except Exception as e:
                        flash(f"Error processing file: {e}", "error")
                    finally:
                        if os.path.exists(filepath):
                            os.remove(filepath)
                else:
                    flash("Invalid file type. Allowed: png, jpg, jpeg, pdf", "error")
                return redirect(url_for("expense"))
            
            # If no file, check for manual entry
            form = request.form
            if "item" in form and "amount" in form and "date" in form and "category" in form:
                try:
                    item = form["item"].strip()
                    amount = float(form["amount"])
                    date_str = form["date"]
                    category = form["category"].strip()
                    
                    # Auto-detect category if not provided or if "Others" is selected using rule-based matching
                    if not category or category == "Others":
                        detected_category = detect_category_from_item(item, item_type='expense', amount=amount)
                        if detected_category:
                            category = detected_category
                    if not category:
                        category = "Others"
                    
                    if mongo.db is not None:
                        user_id_obj = ObjectId(user_id) if user_id else None
                        mongo.db.purchases.insert_one({
                            "user_id": user_id_obj,
                            "item": item,
                            "amount": amount,
                            "date": date_str,
                            "category": category,
                            "created_at": datetime.now(timezone.utc)
                        })
                        flash(f"Manual purchase added: {item} - ₹{amount}", "success")
                    else:
                        flash("Could not connect to database.", "error")
                except ValueError:
                    flash("Amount must be a valid number.", "error")
                except Exception as e:
                    flash(f"Error adding manual purchase: {e}", "error")
                return redirect(url_for("expense"))
        
        # Fetch purchases for the template (same as expense route)
        purchases = []
        total_spent = 0.0
        user_id = session.get('user_id')
        
        if mongo.db is not None and user_id:
            user_id_obj = ObjectId(user_id) if user_id else None
            # Sort by date (newest first), then by created_at, then by _id
            purchases = list(mongo.db.purchases.find({"user_id": user_id_obj}).sort([
                ("date", -1),  # Newest date first
                ("created_at", -1),  # If same date, newest created_at first
                ("_id", -1)  # If same date and created_at, newest _id first
            ]))
            total_spent = sum(p.get('amount', 0.0) for p in purchases)
        
        for p in purchases:
            p['id'] = str(p.pop('_id'))
        
        # Use user's monthly budget for alerting if configured
        settings_doc = {}
        if mongo.db is not None:
            settings_doc = mongo.db.settings.find_one({"user_id": user_id}) or {}
        limits = settings_doc.get("limits", {})
        monthly_budget_limit = float(limits.get("monthly_budget", 0))
        # Compute this month's spending only for alert visibility
        month_key = datetime.today().strftime('%Y-%m')
        month_spent = sum(
            float(p.get('amount', 0.0)) for p in purchases if str(p.get('date','')).startswith(month_key)
        )
        spending_limit_alert = monthly_budget_limit > 0 and month_spent > monthly_budget_limit
        
        # Add summary data
        segments = spending_segments(user_id) if user_id else {}
        breakdown = expense_breakdown_by_subcategory(user_id) if user_id else {}
        
        return render_template("expense.html", date=date, purchases=purchases, alert=spending_limit_alert, total_spent=total_spent, segments=segments, breakdown=breakdown)

    @app.route("/scan-receipt", methods=["GET", "POST"])
    @login_required
    def scan_receipt():
        parsed_info = {"date": None, "company_name": None, "total_amount": None, "raw_text": None}
        if request.method == "POST":
            file = request.files.get("receipt_file")
            if not file or file.filename == '':
                flash("No file selected", "warning")
                return redirect(request.url)
            if not allowed_file(file.filename):
                flash("Invalid file type. Allowed: png, jpg, jpeg, pdf", "error")
                return redirect(request.url)

            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            try:
                parsed_info = process_file_for_extraction(filepath, filename)
                flash("Extracted information from receipt.", "success")
            except Exception as e:
                flash(f"Error processing receipt: {e}", "error")
            finally:
                if os.path.exists(filepath):
                    os.remove(filepath)

        return render_template("scan_receipt.html", parsed_info=parsed_info)

    @app.route('/settings', methods=['GET', 'POST'])
    @login_required
    def settings():
        user_id = session.get('user_id')
        if not user_id:
            flash("User not logged in.", "error")
            return redirect(url_for('login'))
        if request.method == 'POST':
        # Read limits from form
            limits = {
                "monthly_budget": float(request.form.get('monthly_budget', 0)),
                "groceries": float(request.form.get('groceries', 0)),
                "medicine": float(request.form.get('medicine', 0)),
                "toiletries": float(request.form.get('toiletries', 0)),
                "clothes": float(request.form.get('clothes', 0)),
                "stationery": float(request.form.get('stationery', 0)),
                "bills": float(request.form.get('bills', 0)),
                "food": float(request.form.get('food', 0)),
                "transport": float(request.form.get('transport', 0)),
                "miscellaneous": float(request.form.get('miscellaneous', 0)),
            }

        # Save to MongoDB (insert or update)
            mongo.db.settings.update_one(
                {"user_id": user_id},
                {"$set": {"limits": limits}},
                upsert=True
            )

            flash("✅ Settings saved successfully!", "success")
            return redirect(url_for('settings'))

    # Retrieve existing limits if available
        user_limits = mongo.db.settings.find_one({"user_id": user_id})
        limits = user_limits.get("limits", {}) if user_limits else {}

        return render_template('settings.html', limits=limits)

    
    @app.route("/gmail-orders", methods=["GET", "POST"])
    @login_required
    def gmail_orders():
        user_id = session.get('user_id')
        
        # Get recent Gmail imports for display
        gmail_orders = []
        try:
            if mongo.db is not None and user_id:
                print(f"Fetching orders for user_id: {user_id}")  # Debug print
                user_id_obj = ObjectId(user_id) if user_id else None
                query = {
                    "user_id": user_id_obj,
                    "source": {"$in": ["Amazon", "Blinkit"]}
                }
                print(f"MongoDB query: {query}")  # Debug print
                gmail_orders = list(mongo.db.purchases.find(query).sort([("date", -1)]).limit(10))
                print(f"Found {len(gmail_orders)} orders in database")
                
                # Convert ObjectId to string for each order and ensure all fields are present
                for order in gmail_orders:
                    order['_id'] = str(order['_id'])
                    # Ensure order_id exists for display
                    if 'order_id' not in order:
                        order['order_id'] = order.get('item', 'N/A').replace('Order #', '')
                    print(f"Order: {order.get('source')} - {order.get('order_id')} - ₹{order.get('amount', 0)}")
                
                print(f"Found {len(gmail_orders)} Gmail orders") # Debug print
            else:
                print("⚠️ Cannot fetch orders: mongo.db is None or user_id is missing")
        except Exception as e:
            print(f"❌ Error fetching Gmail orders: {e}")
            import traceback
            print(traceback.format_exc())
            gmail_orders = []
        
        if request.method == "POST":
            try:
                # Check if this is a refresh request (no email in form, use stored email)
                email_id = request.form.get('email')
                if not email_id:
                    # Try to get from session (last used email)
                    email_id = session.get('last_gmail_email')
                    if not email_id:
                        flash("Please provide an email address", "error")
                        return redirect(url_for("gmail_orders"))
                
                # Store email in session for future refreshes
                session['last_gmail_email'] = email_id

                # Check if credentials.json exists
                if not os.path.exists(CREDS_FILE):
                    flash("Gmail API credentials not found. Please add credentials.json file to the project folder.", "error")
                    return redirect(url_for("gmail_orders"))

                # Get Gmail service with read-only access
                print(f"Attempting to authenticate with Gmail for: {email_id}")  # Debug print
                try:
                    service = get_gmail_readonly_service(email_id)
                    if not service:
                        print("Gmail authentication failed - service is None")  # Debug print
                        flash("Failed to authenticate with Gmail. Please check your credentials.", "error")
                        return redirect(url_for("gmail_orders"))
                    print("Gmail authentication successful")  # Debug print
                except FileNotFoundError:
                    flash("Gmail credentials file not found. Please add credentials.json to the project folder.", "error")
                    return redirect(url_for("gmail_orders"))
                except Exception as auth_error:
                    print(f"Gmail authentication error: {auth_error}")  # Debug print
                    flash(f"Authentication error: {str(auth_error)}. Please check your Gmail credentials.", "error")
                    return redirect(url_for("gmail_orders"))
                
                # Test the connection by getting user profile
                try:
                    profile = service.users().getProfile(userId='me').execute()
                    print(f"Connected to Gmail account: {profile['emailAddress']}")  # Debug print
                except Exception as e:
                    print(f"Error testing Gmail connection: {e}")  # Debug print
                    flash("Error connecting to Gmail account", "error")
                    return redirect(url_for("gmail_orders"))

                # Get already processed message IDs to skip them
                processed_message_ids = set()
                last_import_date = None
                if mongo.db is not None:
                    user_id_obj = ObjectId(user_id) if user_id else None
                    # Get all already processed Gmail message IDs
                    processed_orders = mongo.db.purchases.find(
                        {
                            "user_id": user_id_obj,
                            "gmail_message_id": {"$exists": True}
                        },
                        {"gmail_message_id": 1, "imported_at": 1}
                    )
                    for order in processed_orders:
                        if order.get("gmail_message_id"):
                            processed_message_ids.add(order["gmail_message_id"])
                        # Track the most recent import date
                        if order.get("imported_at"):
                            import_date = order["imported_at"]
                            if isinstance(import_date, datetime):
                                if last_import_date is None or import_date > last_import_date:
                                    last_import_date = import_date
                            elif isinstance(import_date, str):
                                try:
                                    import_date_parsed = parse(import_date)
                                    if last_import_date is None or import_date_parsed > last_import_date:
                                        last_import_date = import_date_parsed
                                except:
                                    pass
                
                print(f"📋 Already processed {len(processed_message_ids)} messages")
                if last_import_date:
                    print(f"📅 Last import was on: {last_import_date.strftime('%Y-%m-%d %H:%M:%S')}")
                    # Search for emails after the last import date (add 1 day buffer to be safe)
                    date_str = (last_import_date - timedelta(days=1)).strftime('%Y/%m/%d')
                    date_filter = f"after:{date_str}"
                else:
                    date_filter = ""
                    print("📅 No previous imports found, searching all emails")
                
                # Search for Amazon and Blinkit orders - try multiple search strategies
                # Only search for emails after the last import date
                search_queries = [
                    f"in:inbox from:amazon {date_filter}",
                    f"in:inbox from:amazon.in {date_filter}",
                    f"in:inbox from:amazon.com {date_filter}",
                    f"in:inbox (from:no-reply@amazon OR from:auto-confirm@amazon) {date_filter}",
                    f"in:inbox subject:amazon {date_filter}",
                    f"in:inbox from:blinkit {date_filter}",
                    f"in:inbox from:blinkit.com {date_filter}",
                ]
                
                all_messages = []
                seen_message_ids = set()
                
                for search_query in search_queries:
                    print(f"🔍 Searching Gmail with query: {search_query}")
                    messages = gmail_search_messages(service, search_query, max_results=50)
                    if messages:
                        for msg in messages:
                            msg_id = msg['id']
                            # Skip if already seen in this search or already processed
                            if msg_id not in seen_message_ids and msg_id not in processed_message_ids:
                                all_messages.append(msg)
                                seen_message_ids.add(msg_id)
                        print(f"✅ Found {len(messages)} messages with query: {search_query}")
                
                print(f"📧 Total unique NEW messages found: {len(all_messages)} (after filtering processed ones)")
                
                if not all_messages:
                    # Try a broader search if no new messages found
                    print("⚠️ No new messages found with specific queries, trying broader search...")
                    broad_query = f"in:inbox (amazon OR blinkit) {date_filter}"
                    messages = gmail_search_messages(service, broad_query, max_results=100)
                    if messages:
                        for msg in messages:
                            msg_id = msg['id']
                            if msg_id not in seen_message_ids and msg_id not in processed_message_ids:
                                all_messages.append(msg)
                                seen_message_ids.add(msg_id)
                        print(f"✅ Found {len(all_messages)} new messages with broad search")
                
                if not all_messages:
                    if processed_message_ids:
                        flash(f"No new orders found. You have already imported {len(processed_message_ids)} orders.", "info")
                    else:
                        flash("No Amazon or Blinkit order emails found in your inbox. Make sure you have order confirmation emails from Amazon or Blinkit.", "info")
                    return redirect(url_for("gmail_orders"))
                
                messages = all_messages
                print(f"🔄 Processing {len(messages)} new unprocessed messages...")

                orders = []
                for idx, msg in enumerate(messages, 1):
                    print(f"\n{'='*60}")
                    print(f"📨 Processing message {idx}/{len(messages)} - ID: {msg['id']}")
                    body = gmail_get_message_body(service, msg["id"])
                    if body:
                        soup = BeautifulSoup(body, 'html.parser')
                        text = soup.get_text()
                        print(f"📝 Message text length: {len(text)} characters")
                        
                        # Get email subject and from address for debugging
                        try:
                            full_msg = service.users().messages().get(userId="me", id=msg["id"], format="metadata", metadataHeaders=["Subject", "From"]).execute()
                            headers = full_msg.get("payload", {}).get("headers", [])
                            subject = next((h["value"] for h in headers if h["name"] == "Subject"), "No Subject")
                            from_addr = next((h["value"] for h in headers if h["name"] == "From"), "Unknown")
                            print(f"📧 From: {from_addr}")
                            print(f"📋 Subject: {subject}")
                        except Exception as e:
                            print(f"⚠️ Could not get email metadata: {e}")
                            from_addr = ""
                            subject = ""
                        
                        # Extract order details based on email source
                        if "amazon" in text.lower() or "amazon" in from_addr.lower() or "amazon" in subject.lower():  # More permissive check
                            print("Found Amazon email")  # Debug print
                            print("First 500 characters of email:", text[:500])  # Debug print to see email content
                            
                            # Amazon order pattern - try multiple patterns
                            order_id_patterns = [
                                r"order #\s*(\d{3}-\d{7}-\d{7})",
                                r"order number[:\s]+(\d{3}-\d{7}-\d{7})",
                                r"#\s*(\d{3}-\d{7}-\d{7})",
                                r"(\d{3}-\d{7}-\d{7})",
                                r"order[:\s]+(\d{3}-\d{7}-\d{7})"
                            ]
                            
                            order_id_match = None
                            print("Searching for order ID...")  # Debug print
                            for pattern in order_id_patterns:
                                print(f"Trying pattern: {pattern}")  # Debug print
                                order_id_match = re.search(pattern, text, re.IGNORECASE)
                                if order_id_match:
                                    print(f"Found order ID: {order_id_match.group(1)}")  # Debug print
                                    break
                            
                            # Try multiple amount patterns - comprehensive search
                            amount_patterns = [
                                # Patterns with "Total" keyword
                                r"(?:order\s+)?total[:\s]*₹?\s*([\d,]+(?:\.\d{2})?)",
                                r"grand\s+total[:\s]*₹?\s*([\d,]+(?:\.\d{2})?)",
                                r"total\s+amount[:\s]*₹?\s*([\d,]+(?:\.\d{2})?)",
                                r"amount\s+payable[:\s]*₹?\s*([\d,]+(?:\.\d{2})?)",
                                r"total\s+price[:\s]*₹?\s*([\d,]+(?:\.\d{2})?)",
                                # Patterns with "Amount" keyword
                                r"amount[:\s]*₹?\s*([\d,]+(?:\.\d{2})?)",
                                r"order\s+amount[:\s]*₹?\s*([\d,]+(?:\.\d{2})?)",
                                # Direct currency patterns
                                r"₹\s*([\d,]+(?:\.\d{2})?)",
                                r"Rs\.?\s*([\d,]+(?:\.\d{2})?)",
                                r"INR\s*([\d,]+(?:\.\d{2})?)",
                                # Patterns with "paid" or "charged"
                                r"(?:paid|charged)[:\s]*₹?\s*([\d,]+(?:\.\d{2})?)",
                                # Generic number patterns near currency symbols
                                r"₹\s*(\d{1,3}(?:,\d{2,3})*(?:\.\d{2})?)",
                            ]
                            
                            # First, try to find all amounts in the text
                            all_amounts = []
                            for pattern in amount_patterns:
                                matches = re.finditer(pattern, text, re.IGNORECASE)
                                for match in matches:
                                    try:
                                        amount_str = match.group(1).replace(',', '')
                                        amount_val = float(amount_str)
                                        if amount_val > 0:  # Only consider positive amounts
                                            all_amounts.append((amount_val, match.group(0)))
                                    except (ValueError, AttributeError):
                                        continue
                            
                            # If we found multiple amounts, use the largest one (usually the total)
                            amount = 0
                            amount_match = None
                            if all_amounts:
                                # Sort by amount value, take the largest
                                all_amounts.sort(key=lambda x: x[0], reverse=True)
                                amount = all_amounts[0][0]
                                amount_match = True
                                print(f"💰 Found {len(all_amounts)} amount(s), using largest: ₹{amount}")
                                if len(all_amounts) > 1:
                                    print(f"   Other amounts found: {[f'₹{a[0]}' for a in all_amounts[1:5]]}")
                            else:
                                # Fallback: try to find any number with ₹ symbol
                                print("⚠️ No amount found with patterns, trying fallback search...")
                                fallback_patterns = [
                                    r"₹\s*(\d+(?:,\d{3})*(?:\.\d{2})?)",
                                    r"(\d+(?:,\d{3})*(?:\.\d{2})?)\s*₹",
                                ]
                                for pattern in fallback_patterns:
                                    matches = re.finditer(pattern, text, re.IGNORECASE)
                                    fallback_amounts = []
                                    for match in matches:
                                        try:
                                            amount_str = match.group(1).replace(',', '')
                                            amount_val = float(amount_str)
                                            if amount_val >= 10:  # Reasonable minimum
                                                fallback_amounts.append(amount_val)
                                        except (ValueError, AttributeError):
                                            continue
                                    if fallback_amounts:
                                        amount = max(fallback_amounts)
                                        amount_match = True
                                        print(f"💰 Found amount via fallback: ₹{amount}")
                                        break
                                
                                if not amount_match:
                                    print("❌ Could not extract amount from email")
                            
                            # Try multiple date patterns
                            date_patterns = [
                                r"(?:ordered on|order placed|date)[:\s]*([A-Za-z]+\s+\d{1,2},?\s+\d{4})",
                                r"([A-Za-z]+\s+\d{1,2},?\s+\d{4})",
                                r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})"
                            ]
                            
                            date_match = None
                            print("Searching for date...")  # Debug print
                            for pattern in date_patterns:
                                print(f"Trying date pattern: {pattern}")  # Debug print
                                date_match = re.search(pattern, text, re.IGNORECASE)
                                if date_match:
                                    print(f"Found date: {date_match.group(1)}")  # Debug print
                                    break
                            if order_id_match:
                                print("\nProcessing Amazon order:")  # Debug print
                                print(f"Order ID: {order_id_match.group(1)}")
                                
                                # Default to current date if no date found
                                order_date = datetime.now()
                                if date_match:
                                    try:
                                        order_date = parse(date_match.group(1))
                                        print(f"Parsed date: {order_date}")
                                    except Exception as e:
                                        print(f"Error parsing date: {e}")
                                
                                # Amount is already processed above with comprehensive search
                                if not amount_match:
                                    print("⚠️ Warning: No amount found, setting to 0")
                                    amount = 0
                                else:
                                    print(f"✅ Final parsed amount: ₹{amount}")
                                
                                # Format date as string for database
                                date_str = order_date.strftime('%Y-%m-%d') if isinstance(order_date, datetime) else datetime.now().strftime('%Y-%m-%d')
                                
                                order_details = {
                                    "user_id": ObjectId(user_id),
                                    "order_id": order_id_match.group(1),
                                    "amount": amount,
                                    "date": date_str,
                                    "source": "Amazon",
                                    "category": "Shopping",
                                    "item": f"Amazon Order #{order_id_match.group(1)}",
                                    "description": f"Amazon Order #{order_id_match.group(1)}",
                                    "gmail_imported": True,
                                    "gmail_message_id": msg["id"],
                                    "imported_at": datetime.now(timezone.utc),
                                    "last_checked": datetime.now(timezone.utc),
                                    "created_at": datetime.now(timezone.utc)
                                }
                                print("Created order details:", order_details)
                                
                                # Check for duplicates using multiple methods for robust tracking
                                if mongo.db is not None:
                                    # Check by order_id (primary method)
                                    existing_by_order_id = mongo.db.purchases.find_one({
                                        "user_id": ObjectId(user_id),
                                        "order_id": order_id_match.group(1)
                                    })
                                    
                                    # Also check by Gmail message ID (secondary method)
                                    existing_by_msg_id = mongo.db.purchases.find_one({
                                        "user_id": ObjectId(user_id),
                                        "gmail_message_id": msg["id"]
                                    })
                                    
                                    if existing_by_order_id or existing_by_msg_id:
                                        # Order already exists - update last_checked timestamp
                                        existing_order = existing_by_order_id or existing_by_msg_id
                                        mongo.db.purchases.update_one(
                                            {"_id": existing_order["_id"]},
                                            {"$set": {"last_checked": datetime.utcnow()}}
                                        )
                                        print(f"⚠️ Order {order_id_match.group(1)} already exists (ID: {existing_order.get('_id')}), updated tracking timestamp")
                                    else:
                                        try:
                                            mongo.db.purchases.insert_one(order_details)
                                            orders.append(order_details)
                                            print(f"✅ Successfully inserted Amazon order: {order_id_match.group(1)}")
                                        except Exception as insert_error:
                                            print(f"❌ Error inserting order: {insert_error}")
                                            import traceback
                                            print(traceback.format_exc())
                                else:
                                    print("❌ MongoDB connection not available")
                            else:
                                print("⚠️ Amazon order found but order_id not matched, skipping")
                        
                        elif "blinkit" in text.lower():
                            # Blinkit order pattern
                            order_id_match = re.search(r"(?:order id:|order number:)\s*([A-Z0-9-]+)", text, re.IGNORECASE)
                            amount_match = re.search(r"(?:total|amount|paid):\s*₹\s*([\d,]+\.?\d*)", text, re.IGNORECASE)
                            date_match = re.search(r"(?:ordered on|date:)\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})", text, re.IGNORECASE)
                            
                            if order_id_match and amount_match:
                                order_date = parse(date_match.group(1)) if date_match else datetime.now()
                                amount = float(amount_match.group(1).replace(',', ''))
                                # Format date as string for database
                                date_str = order_date.strftime('%Y-%m-%d') if isinstance(order_date, datetime) else datetime.now().strftime('%Y-%m-%d')
                                
                                order_details = {
                                    "user_id": ObjectId(user_id),
                                    "order_id": order_id_match.group(1),
                                    "amount": amount,
                                    "date": date_str,
                                    "source": "Blinkit",
                                    "category": "Groceries",
                                    "item": f"Blinkit Order #{order_id_match.group(1)}",
                                    "description": f"Blinkit Order #{order_id_match.group(1)}",
                                    "gmail_imported": True,
                                    "gmail_message_id": msg["id"],
                                    "imported_at": datetime.now(timezone.utc),
                                    "last_checked": datetime.now(timezone.utc),
                                    "created_at": datetime.now(timezone.utc)
                                }
                                
                                # Check for duplicates using multiple methods for robust tracking
                                if mongo.db is not None:
                                    # Check by order_id (primary method)
                                    existing_by_order_id = mongo.db.purchases.find_one({
                                        "user_id": ObjectId(user_id),
                                        "order_id": order_id_match.group(1)
                                    })
                                    
                                    # Also check by Gmail message ID (secondary method)
                                    existing_by_msg_id = mongo.db.purchases.find_one({
                                        "user_id": ObjectId(user_id),
                                        "gmail_message_id": msg["id"]
                                    })
                                    
                                    if existing_by_order_id or existing_by_msg_id:
                                        # Order already exists - update last_checked timestamp
                                        existing_order = existing_by_order_id or existing_by_msg_id
                                        mongo.db.purchases.update_one(
                                            {"_id": existing_order["_id"]},
                                            {"$set": {"last_checked": datetime.utcnow()}}
                                        )
                                        print(f"⚠️ Order {order_id_match.group(1)} already exists (ID: {existing_order.get('_id')}), updated tracking timestamp")
                                    else:
                                        try:
                                            mongo.db.purchases.insert_one(order_details)
                                            orders.append(order_details)
                                            print(f"✅ Successfully inserted Blinkit order: {order_id_match.group(1)}")
                                        except Exception as insert_error:
                                            print(f"❌ Error inserting order: {insert_error}")
                                            import traceback
                                            print(traceback.format_exc())
                                else:
                                    print("❌ MongoDB connection not available")

                if orders:
                    flash(f"Successfully imported {len(orders)} orders from Gmail", "success")
                else:
                    flash("No new orders found to import", "info")
                
                return redirect(url_for("gmail_orders"))
            
            except Exception as e:
                import traceback
                error_details = traceback.format_exc()
                print(f"Error processing Gmail orders: {error_details}")  # Debug print
                flash(f"Error importing orders: {str(e)}. Check console for details.", "error")
                return redirect(url_for("gmail_orders"))

        # Get last used email from session for display
        last_email = session.get('last_gmail_email', '')
        return render_template("gmail_orders.html", gmail_orders=gmail_orders, last_email=last_email)

    @app.route("/dbtest")
    def dbcheck():
        try:
            db_name = mongo.db.name
            collections = mongo.db.list_collection_names()
            return f"✅ Connected to DB: {db_name}, collections: {collections}"
        except Exception as e:
            return f"❌ MongoDB error: {str(e)}"

    @app.route('/savings')
    @login_required
    def savings():
        user_id = session.get('user_id')
        user_email = session.get('user_email')
        
        # 1. Goals I am a member of (or owner)
        my_goals = list(mongo.db.savings_goals.find({
            "$or": [
                {"owner_id": user_id},
                {"members": user_id}
            ]
        }))

        # 2. Invitations pending for me
        pending_invites_for_render = []
        invite_goals = mongo.db.savings_goals.find({"pending_invites.email": user_email})
        
        for goal in invite_goals:
            for invite in goal.get('pending_invites', []):
                if invite['email'] == user_email:
                    # Look up sender details
                    sender = mongo.db.users.find_one({"_id": ObjectId(invite['sender_id'])}, {"fullname": 1})
                    
                    pending_invites_for_render.append({
                        "goal_id": str(goal['_id']),
                        "goal_name": goal['name'],
                        "sender_name": sender.get('fullname', 'Unknown User') if sender else 'Unknown User',
                        "invite_id": str(invite['_id']),
                    })
                    break # Only need one invite per goal for this user

        return render_template("savings.html", my_goals=my_goals, pending_invites=pending_invites_for_render)
    
    # --- NEW SAVINGS GOAL ROUTES ---

    @app.route("/savings/create", methods=["POST"])
    @login_required
    def create_savings_goal():
        user_id = session.get('user_id')
        user_name = session.get('user_name') # Assumed to be available
        user_email = session.get('user_email')
        
        goal_name = request.form.get("goal_name")
        goal_type = request.form.get("goal_type") # e.g., 'Event:Wedding'
        specific_type = request.form.get("specific_type", "")  # e.g., 'Wedding'
        invite_email = request.form.get("invite_email", "").lower()
        
        # If goal_type is not provided but specific_type is, construct goal_type
        if not goal_type and specific_type:
            goal_type = f"Event:{specific_type}"  # Default to Event type
        
        if not goal_name:
            flash("Goal name is required.", "error")
            return redirect(url_for('savings'))
        
        if not goal_type:
            flash("Goal type is required. Please select a goal type.", "error")
            return redirect(url_for('savings'))
        
        success_messages = [f"Savings Goal '{goal_name}' created successfully!"]
        
        try:
            # --- 1. Create the Goal Document ---
            new_goal = {
                "name": goal_name,
                "type": goal_type,
                "owner_id": user_id,
                "owner_name": user_name,
                "members": [user_id],  # Owner is the first member
                "pending_invites": [],
                "categories": [],       # Sub-categories (Decoration, Food, etc.)
                "created_at": datetime.utcnow()
            }
            result = mongo.db.savings_goals.insert_one(new_goal)
            goal_id = str(result.inserted_id)
            
            # --- 2. Handle Optional Invitation ---
            if invite_email and invite_email != user_email:
                invite_id = ObjectId()
                mongo.db.savings_goals.update_one(
                    {"_id": result.inserted_id},
                    {"$push": {
                        "pending_invites": {
                            "_id": invite_id,
                            "email": invite_email,
                            "sender_id": user_id,
                            "sent_at": datetime.utcnow()
                        }
                    }}
                )
                success_messages.append(f"Invitation sent to {invite_email}.")
            elif invite_email == user_email:
                success_messages.append("Note: Cannot invite yourself. Invitation skipped.")
            
            flash(" ".join(success_messages), "success")
            return redirect(url_for('savings_goal_details', goal_id=goal_id))
            
        except Exception as e:
            flash(f"Could not create goal or send invitation: {e}", "error")
            return redirect(url_for('savings'))

    @app.route("/savings/accept_invite/<goal_id>/<invite_id>", methods=["POST"])
    @login_required
    def accept_savings_invite(goal_id, invite_id):
        user_id = session.get('user_id')
        user_email = session.get('user_email')
        
        try:
            # 1. Pull the invite from pending_invites
            update_result = mongo.db.savings_goals.update_one(
                {"_id": ObjectId(goal_id)},
                {
                    "$pull": {
                        "pending_invites": {
                            "_id": ObjectId(invite_id),
                            "email": user_email 
                        }
                    }
                }
            )

            if update_result.modified_count == 0:
                flash("Invitation not found or has expired.", "error")
                return redirect(url_for('savings'))

            # 2. Add user to members list
            goal = mongo.db.savings_goals.find_one_and_update(
                {"_id": ObjectId(goal_id)},
                {"$addToSet": {"members": user_id}}, # $addToSet prevents duplicates
                return_document=True
            )
            
            if goal:
                flash(f"You have joined the savings goal '{goal['name']}'!", "success")
                return redirect(url_for('savings_goal_details', goal_id=goal_id))
            else:
                flash("Goal was deleted. Could not join.", "error")

        except Exception as e:
            flash(f"Error accepting invitation: {e}", "error")
            
        return redirect(url_for('savings'))


    @app.route("/savings/<goal_id>", methods=["GET"])
    @login_required
    def savings_goal_details(goal_id):
        user_id = session.get('user_id')
        
        try:
            goal = mongo.db.savings_goals.find_one({"_id": ObjectId(goal_id)})

            if not goal or (goal['owner_id'] != user_id and user_id not in goal['members']):
                flash("Savings Goal not found or you are not a member.", "error")
                return redirect(url_for('savings'))

            # Fetch all contributions for this goal
            all_contributions = list(mongo.db.goal_contributions.find({"goal_id": goal_id}).sort("contributed_at", -1))

            # Fetch user details for all members/owner to map IDs to names
            member_ids = [ObjectId(goal['owner_id'])] + [ObjectId(m) for m in goal['members'] if m != goal['owner_id']]
            member_map = {str(m['_id']): m['fullname'] for m in mongo.db.users.find({"_id": {"$in": member_ids}}, {"fullname": 1})}

            # Prepare categories with contribution data
            goal_categories_for_render = []
            
            for cat in goal.get('categories', []):
                cat_id = str(cat['_id'])
                target = cat['target_amount']
                
                # Filter contributions for this category
                category_contributions = [c for c in all_contributions if c['category_id'] == cat_id]
                
                # Calculate total saved
                total_saved = sum(c['amount'] for c in category_contributions)
                progress = min(100, (total_saved / target) * 100) if target > 0 else 0
                
                # Group contributions by member for the details list
                member_contributions_detail = {}
                for m_id in member_ids:
                    member_id_str = str(m_id)
                    member_contributions_detail[member_id_str] = {
                        "name": member_map.get(member_id_str, "Unknown"), 
                        "total_given": sum(c['amount'] for c in category_contributions if c['contributor_id'] == member_id_str)
                    }

                goal_categories_for_render.append({
                    "id": cat_id,
                    "name": cat['name'],
                    "target_amount": target,
                    "total_saved": total_saved,
                    "progress": round(progress, 2),
                    "member_contributions": list(member_contributions_detail.values()),
                    "latest_contributions": [{
                        "contributor_name": member_map.get(c['contributor_id'], "Unknown"),
                        "amount": c['amount'],
                        "date": c['contributed_at'].strftime("%Y-%m-%d") if isinstance(c['contributed_at'], datetime) else c['contributed_at']
                    } for c in category_contributions[:5]]
                })
            
            # Prepare all member totals across all categories for the main chart
            member_overall_totals = {str(m_id): {"name": member_map.get(str(m_id), "Unknown"), "total_given": 0.0} for m_id in member_ids}
            for contribution in all_contributions:
                contributor_id = contribution.get('contributor_id')
                if contributor_id in member_overall_totals:
                    member_overall_totals[contributor_id]['total_given'] += contribution.get('amount', 0)


            is_owner = (goal['owner_id'] == user_id)
            
            # Get owner name for display
            owner_user = mongo.db.users.find_one({"_id": ObjectId(goal['owner_id'])}, {"fullname": 1})
            owner_name = owner_user.get('fullname', 'Unknown') if owner_user else 'Unknown'
            
            # Calculate combined totals for all members
            combined_total = sum(m['total_given'] for m in member_overall_totals.values())
            
            # Get all member names with their details
            all_member_details = []
            for m_id in member_ids:
                m_id_str = str(m_id)
                member_user = mongo.db.users.find_one({"_id": ObjectId(m_id)}, {"fullname": 1, "email": 1})
                all_member_details.append({
                    "id": m_id_str,
                    "name": member_map.get(m_id_str, "Unknown"),
                    "email": member_user.get('email', '') if member_user else '',
                    "is_owner": m_id_str == str(goal['owner_id']),
                    "total_contributed": member_overall_totals.get(m_id_str, {}).get('total_given', 0.0)
                })

            return render_template(
                'savings_detail.html',
                goal=goal,
                goal_id=goal_id,
                goal_categories=goal_categories_for_render,
                member_overall_totals=list(member_overall_totals.values()),
                all_member_details=all_member_details,
                owner_name=owner_name,
                combined_total=combined_total,
                is_owner=is_owner,
                date = datetime.now().date()
            )
            
        except Exception as e:
            flash(f"An error occurred while fetching goal details: {e}", "error")
            return redirect(url_for('savings'))


    @app.route("/savings/<goal_id>/add_category", methods=["POST"])
    @login_required
    def add_goal_category(goal_id):
        user_id = session.get('user_id')
        
        try:
            goal = mongo.db.savings_goals.find_one({"_id": ObjectId(goal_id)})
            if not goal or (user_id not in goal['members']):
                flash("Goal not found or you are not a member.", "error")
                return redirect(url_for('savings'))
                
            category_name = request.form.get('category_name')
            target_amount = float(request.form.get('target_amount'))
            
            if not category_name or target_amount is None:
                flash("Category name and target amount are required.", "error")
                return redirect(url_for('savings_goal_details', goal_id=goal_id))

            if target_amount <= 0:
                 flash("Target amount must be greater than zero.", "error")
                 return redirect(url_for('savings_goal_details', goal_id=goal_id))

            new_category = {
                "_id": ObjectId(),
                "name": category_name,
                "target_amount": target_amount,
                "created_at": datetime.utcnow()
            }
            
            mongo.db.savings_goals.update_one(
                {"_id": ObjectId(goal_id)},
                {"$push": {"categories": new_category}}
            )
            
            flash(f"Savings category '{category_name}' with a target of {target_amount} added.", "success")

        except ValueError:
            flash("Invalid input. Please enter a valid number for target amount.", "error")
        except Exception as e:
            flash(f"An error occurred: {e}", "error")

        return redirect(url_for('savings_goal_details', goal_id=goal_id))

    @app.route("/savings/<goal_id>/invite", methods=["POST"])
    @login_required
    def invite_savings_member(goal_id):
        user_id = session.get('user_id')
        user_email = session.get('user_email')
        invite_email = request.form.get('invite_email', '').lower().strip()
        
        if not invite_email:
            flash("Please provide an email address.", "error")
            return redirect(url_for('savings_goal_details', goal_id=goal_id))
        
        try:
            goal = mongo.db.savings_goals.find_one({"_id": ObjectId(goal_id)})
            if not goal:
                flash("Goal not found.", "error")
                return redirect(url_for('savings'))
            
            # Check permissions - convert members to strings for comparison
            members_str = [str(m) for m in goal.get('members', [])]
            owner_id_str = str(goal.get('owner_id', ''))
            
            if user_id not in members_str and owner_id_str != user_id:
                flash("You don't have permission to invite to this goal.", "error")
                return redirect(url_for('savings'))
            
            # Check if user is already a member
            invited_user = mongo.db.users.find_one({"email": invite_email})
            if invited_user:
                invited_user_id_str = str(invited_user['_id'])
                if invited_user_id_str in members_str:
                    flash(f"User {invite_email} is already a member.", "warning")
                    return redirect(url_for('savings_goal_details', goal_id=goal_id))
            
            # Check if invitation already pending
            if any(invite['email'] == invite_email for invite in goal.get('pending_invites', [])):
                flash(f"Invitation already pending for {invite_email}.", "warning")
                return redirect(url_for('savings_goal_details', goal_id=goal_id))
            
            # Create invitation
            invite_id = ObjectId()
            mongo.db.savings_goals.update_one(
                {"_id": ObjectId(goal_id)},
                {"$push": {
                    "pending_invites": {
                        "_id": invite_id,
                        "email": invite_email,
                        "sender_id": user_id,
                        "sent_at": datetime.utcnow()
                    }
                }}
            )
            
            flash(f"Invitation sent to {invite_email}. They can accept it from their Savings page.", "success")
            
        except Exception as e:
            flash(f"Error sending invitation: {e}", "error")
        
        return redirect(url_for('savings_goal_details', goal_id=goal_id))


    @app.route("/savings/<goal_id>/<category_id>/add_contribution", methods=["POST"])
    @login_required
    def add_goal_contribution(goal_id, category_id):
        user_id = session.get('user_id')
        
        try:
            goal = mongo.db.savings_goals.find_one({"_id": ObjectId(goal_id)})
            if not goal or (user_id not in goal['members']):
                flash("Goal not found or you are not a member.", "error")
                return redirect(url_for('savings'))
                
            amount = float(request.form.get('contribution_amount'))
            date_str = request.form.get('contribution_date')
            
            if not all([amount, date_str]):
                flash("Contribution amount and date are required.", "error")
                return redirect(url_for('savings_goal_details', goal_id=goal_id))

            if amount <= 0:
                 flash("Contribution amount must be greater than zero.", "error")
                 return redirect(url_for('savings_goal_details', goal_id=goal_id))
            
            # Simple check if category exists in goal
            if not any(str(c['_id']) == category_id for c in goal.get('categories', [])):
                flash("Category not found in this goal.", "error")
                return redirect(url_for('savings_goal_details', goal_id=goal_id))

            contribution_entry = {
                "goal_id": goal_id,
                "category_id": category_id,
                "contributor_id": user_id, 
                "amount": amount,
                "date": date_str,
                "contributed_at": datetime.utcnow()
            }
            mongo.db.goal_contributions.insert_one(contribution_entry)
            flash(f"Contribution of {amount} added successfully.", "success")

        except ValueError:
            flash("Invalid input. Please enter a valid number for amount.", "error")
        except Exception as e:
            flash(f"An error occurred: {e}", "error")

        return redirect(url_for('savings_goal_details', goal_id=goal_id))

    # --- EXISTING GROUP SHARING ROUTES (UNCHANGED) ---
    # ... (Keep your original @app.route("/groups"), @app.route("/group/create"),
    # @app.route("/group/invite/<group_id>"), @app.route("/groups/accept_invite/<group_id>/<invite_id>"),
    # @app.route("/group/<group_id>") and @app.route("/group/<group_id>/add_expense" routes here) ...

    # The original group routes provided in the prompt are kept here:

    @app.route("/groups")
    @login_required
    def groups():
        user_id = session.get('user_id')

        # 1. Groups I am a member of (or owner)
        my_groups = list(mongo.db.groups.find({
            "$or": [
                {"owner_id": user_id},
                {"members": user_id}
            ]
        }))

        # 2. Invitations pending for me (where my email is in pending_invites.email)
        my_pending_invites = list(mongo.db.groups.aggregate([
            { "$match": { "pending_invites.email": session.get('user_email') } },
            { "$unwind": "$pending_invites" },
            { "$match": { "pending_invites.email": session.get('user_email') } },
            { "$lookup": {
                "from": "users",
                "localField": "pending_invites.sender_id",
                "foreignField": "_id",
                "as": "sender_info"
            }},
            { "$unwind": { "path": "$sender_info", "preserveNullAndEmptyArrays": True } },
            { "$project": {
                "_id": "$pending_invites._id",  # The invite ID (temporary use)
                "group_id": "$_id",
                "group_name": "$name",
                "sender_name": "$sender_info.fullname",
                "invite_date": "$pending_invites.sent_at"
            }}
        ]))
        
        # We need to map the full group documents to the simplified invite structure
        # A simpler approach: get the list of group_ids and fetch details
        invite_groups = mongo.db.groups.find({"pending_invites.email": session.get('user_email')})
        
        # Prepare the data structure for the template
        pending_invites_for_render = []
        for group in invite_groups:
            for invite in group.get('pending_invites', []):
                if invite['email'] == session.get('user_email'):
                    sender = mongo.db.users.find_one({"_id": ObjectId(invite['sender_id'])})
                    
                    # Create a unique ID for this invite (Group ID + Invite ID)
                    invite_render_id = str(group['_id']) + ":" + str(invite['_id'])
                    
                    pending_invites_for_render.append({
                        "group_id": str(group['_id']),
                        "group_name": group['name'],
                        "sender_name": sender.get('fullname', 'Unknown User') if sender else 'Unknown User',
                        "invite_id": str(invite['_id']),
                        "invite_render_id": invite_render_id
                    })
                    break # Only need one invite per group for this user

        return render_template('groups.html', my_groups=my_groups, pending_invites=pending_invites_for_render)

    @app.route("/group/create", methods=["POST"])
    @login_required
    def create_group():
        # Get current user details
        user_id = session.get('user_id')
        user_name = session.get('user_name')
        user_email = session.get('user_email')
        
        # Get form data
        group_name = request.form.get("group_name")
        # Get and normalize the optional invite email
        invite_email = request.form.get("invite_email", "").lower()
        
        if not group_name:
            flash("Group name is required.", "error")
            return redirect(url_for('groups'))
        
        # Start a list to collect messages for the user
        success_messages = [f"Group '{group_name}' created successfully! You are the owner."]
        
        try:
            # --- 1. Create the Group Document ---
            new_group = {
                "name": group_name,
                "owner_id": user_id,
                "owner_name": user_name,
                "members": [user_id],
                "pending_invites": [],
                "created_at": datetime.utcnow()
            }
            result = mongo.db.groups.insert_one(new_group)
            group_id = str(result.inserted_id)
            
            # --- 2. Handle Optional Invitation ---
            if invite_email:
                if invite_email == user_email:
                    # Self-invitation check
                    success_messages.append("Note: Cannot invite yourself. Invitation skipped.")
                else:
                    # Create a unique ID for the invite itself
                    invite_id = ObjectId()
                    
                    # Add pending invite to the new group's document
                    mongo.db.groups.update_one(
                        {"_id": result.inserted_id},
                        {"$push": {
                            "pending_invites": {
                                "_id": invite_id,
                                "email": invite_email,
                                "sender_id": user_id,
                                "sent_at": datetime.utcnow()
                            }
                        }}
                    )
                    success_messages.append(f"Invitation sent to {invite_email}. They must accept on their Groups page.")
                    
            # Combine all messages and flash to the user
            flash(" ".join(success_messages), "success")
            return redirect(url_for('group_details', group_id=group_id))
            
        except Exception as e:
            flash(f"Could not create group or send invitation: {e}", "error")
            return redirect(url_for('groups'))


    @app.route("/group/invite/<group_id>", methods=["POST"])
    @login_required
    def invite_member(group_id):
        user_id = session.get('user_id')
        invite_email = request.form.get("invite_email", "").lower()
        
        try:
            group = mongo.db.groups.find_one({"_id": ObjectId(group_id)})
            if not group or (group['owner_id'] != user_id and user_id not in group['members']):
                flash("Group not found or you don't have permission to invite.", "error")
                return redirect(url_for('groups'))

            invited_user = mongo.db.users.find_one({"email": invite_email})
            
            if invited_user and str(invited_user['_id']) in group['members']:
                flash(f"User {invite_email} is already a member.", "warning")
                return redirect(url_for('group_details', group_id=group_id))
                
            if any(invite['email'] == invite_email for invite in group.get('pending_invites', [])):
                flash(f"Invitation already pending for {invite_email}.", "warning")
                return redirect(url_for('group_details', group_id=group_id))
                
            # Create a unique ID for the invite itself
            invite_id = ObjectId()
            
            # Add pending invite to the group
            mongo.db.groups.update_one(
                {"_id": ObjectId(group_id)},
                {"$push": {
                    "pending_invites": {
                        "_id": invite_id,
                        "email": invite_email,
                        "sender_id": user_id,
                        "sent_at": datetime.utcnow()
                    }
                }}
            )
            flash(f"Invitation sent to {invite_email}. They must accept on their Groups page.", "success")
            
        except Exception as e:
            flash(f"Error sending invitation: {e}", "error")
            
        return redirect(url_for('group_details', group_id=group_id))
    
    @app.route("/groups/accept_invite/<group_id>/<invite_id>", methods=["POST"])
    @login_required
    def accept_invite(group_id, invite_id):
        user_id = session.get('user_id')
        user_email = session.get('user_email')
        
        try:
            # 1. Pull the invite from pending_invites
            # We use arrayFilters to ensure we only remove the specific invite for the current user's email
            update_result = mongo.db.groups.update_one(
                {"_id": ObjectId(group_id)},
                {
                    "$pull": {
                        "pending_invites": {
                            "_id": ObjectId(invite_id),
                            "email": user_email
                        }
                    }
                }
            )

            if update_result.modified_count == 0:
                flash("Invitation not found or has expired.", "error")
                return redirect(url_for('groups'))

            # 2. Add user to members list
            group = mongo.db.groups.find_one_and_update(
                {"_id": ObjectId(group_id)},
                {"$addToSet": {"members": user_id}}, # $addToSet prevents duplicates
                return_document=True
            )
            
            if group:
                flash(f"You have joined the group '{group['name']}'!", "success")
                return redirect(url_for('group_details', group_id=group_id))
            else:
                flash("Group was deleted. Could not join.", "error")

        except Exception as e:
            flash(f"Error accepting invitation: {e}", "error")
            
        return redirect(url_for('groups'))


    @app.route("/group/<group_id>", methods=["GET"])
    @login_required
    def group_details(group_id):
        user_id = session.get('user_id')
        
        try:
            group = mongo.db.groups.find_one({"_id": ObjectId(group_id)})

            if not group or (group['owner_id'] != user_id and user_id not in group['members']):
                flash("Group not found or you are not a member.", "error")
                return redirect(url_for('groups'))

            # Fetch all expenses for this group
            group_expenses = list(mongo.db.group_expenses.find({"group_id": group_id}).sort("date", -1))
            
            # Fetch user details for all members/owner to map IDs to names
            member_ids = [ObjectId(group['owner_id'])] + [ObjectId(m) for m in group['members'] if m != group['owner_id']]
            
            members_data = list(mongo.db.users.find({"_id": {"$in": member_ids}}, {"fullname": 1}))
            member_map = {str(m['_id']): m['fullname'] for m in members_data}
            
            # Calculate total expenses by each member
            member_totals = {}
            for m_id in member_ids:
                member_totals[str(m_id)] = {"name": member_map.get(str(m_id), "Unknown"), "total_paid": 0.0}

            for expense in group_expenses:
                expense['id'] = str(expense.pop('_id'))
                payer_id = expense.get('payer_id')
                expense['payer_name'] = member_map.get(payer_id, "Unknown User")
                
                # Sum up total paid by each member
                if payer_id in member_totals:
                    member_totals[payer_id]['total_paid'] += expense.get('amount', 0)
            
            # Convert member_totals dict to a list for easier template iteration
            member_totals_list = list(member_totals.values())
            
            # Check if user is the owner
            is_owner = (group['owner_id'] == user_id)

            return render_template(
                'group_details.html',
                group=group,
                group_id=group_id,
                group_expenses=group_expenses,
                member_totals=member_totals_list,
                is_owner=is_owner,
                date=date
            )
            
        except Exception as e:
            flash(f"An error occurred while fetching group details: {e}", "error")
            return redirect(url_for('groups'))

    @app.route("/group/<group_id>/add_expense", methods=["POST"])
    @login_required
    def add_group_expense(group_id):
        user_id = session.get('user_id')
        
        # Check if user is a member of the group
        group = mongo.db.groups.find_one({"_id": ObjectId(group_id)})
        if not group or (group['owner_id'] != user_id and user_id not in group['members']):
            flash("Group not found or you are not a member.", "error")
            return redirect(url_for('groups'))
            
        try:
            item = request.form.get('item')
            amount = float(request.form.get('amount'))
            date_str = request.form.get('date')
            
            if not all([item, amount, date_str]):
                flash("All fields (item, amount, date) are required.", "error")
                return redirect(url_for('group_details', group_id=group_id))

            expense_entry = {
                "group_id": group_id,
                "payer_id": user_id, # The current user is the one who paid/entered the expense
                "item": item,
                "amount": amount,
                "date": date_str,
                "created_at": datetime.utcnow()
            }
            mongo.db.group_expenses.insert_one(expense_entry)
            flash(f"Expense '{item}' of {amount} added to the group.", "success")

        except ValueError:
            flash("Invalid input. Please enter a valid number for amount.", "error")
        except Exception as e:
            flash(f"An error occurred: {e}", "error")

        return redirect(url_for('group_details', group_id=group_id))
    @app.route('/api/budget-data')
    @login_required
    def get_budget_data():
        user_id = session.get('user_id')

    # Fetch user's limits from settings document to stay consistent with Settings page
        user_id_obj = ObjectId(user_id) if user_id else None
        settings_doc = {}
        if mongo.db is not None:
            settings_doc = mongo.db.settings.find_one({"user_id": user_id_obj}) or {}
        limits = settings_doc.get("limits", {})

    # Overall monthly budget
        overall_budget = float(limits.get("monthly_budget", 0))

    # Fetch all expenses and group by category
        expenses_cursor = []
        if mongo.db is not None:
            expenses_cursor = mongo.db.purchases.find({"user_id": user_id_obj})
        expenses_by_category = {}
        total_expenses = 0

        for e in expenses_cursor:
            category = e.get("category", "Others")
            amount = float(e.get("amount", 0))
            total_expenses += amount
            expenses_by_category[category] = expenses_by_category.get(category, 0) + amount

    # Fetch category-specific limits (all non-monthly keys in limits)
        category_limits = {k: v for k, v in limits.items() if k != "monthly_budget"}

    # Prepare structured data for frontend
        category_budgets = {}
        for category, spent in expenses_by_category.items():
            category_budget = float(category_limits.get(category, 0)) if category in category_limits else 0.0
            category_budgets[category] = {
                "budget": category_budget,
                "spent": spent
            }

        data = {
            "overallBudget": overall_budget,
            "totalExpenses": total_expenses,
            "categoryBudgets": category_budgets
        }

        return jsonify(data)

    # --- ML FEATURES ---
    try:
        from ml_features.routes import ml_bp
        app.register_blueprint(ml_bp)
        print("✅ ML Features registered")
    except Exception as e:
        print(f"⚠️ ML Features not available: {e}")
        # ML features are optional, don't break the app if they fail

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5002)