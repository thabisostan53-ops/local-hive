import os
import hashlib
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, abort, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///local_hive.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# File upload configuration
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5MB

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# Ensure upload directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize database
db = SQLAlchemy(app)

# ============================================
# DATABASE MODELS
# ============================================

class Listing(db.Model):
    """Product/Service listing model"""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(200), nullable=False)
    
    # Contact details (seller chooses what to share)
    phone = db.Column(db.String(50))
    email = db.Column(db.String(100))
    whatsapp = db.Column(db.String(50))
    
    # Images
    image_filename = db.Column(db.String(255))
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, default=lambda: datetime.utcnow() + timedelta(days=30))
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    
    # Admin fields (for spam prevention)
    admin_approved = db.Column(db.Boolean, default=False)
    is_reported = db.Column(db.Boolean, default=False)
    
    def __repr__(self):
        return f'<Listing {self.title}>'

# ============================================
# HELPER FUNCTIONS
# ============================================

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_slug(title):
    """Generate URL-friendly slug from title"""
    return '-'.join(title.lower().split())[:50]

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('Please login as admin to access this page.', 'error')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# ============================================
# ROUTES
# ============================================

@app.route('/')
def index():
    """Homepage - show all active listings"""
    # Get filter parameters
    category = request.args.get('category', 'all')
    search = request.args.get('search', '')
    location = request.args.get('location', '')
    
    query = Listing.query.filter_by(is_active=True, admin_approved=True)
    
    if category != 'all':
        query = query.filter_by(category=category)
    
    if search:
        query = query.filter(
            db.or_(
                Listing.title.contains(search),
                Listing.description.contains(search)
            )
        )
    
    if location:
        query = query.filter(Listing.location.contains(location))
    
    listings = query.order_by(Listing.created_at.desc()).all()
    
    # Get unique categories for filter
    categories = db.session.query(Listing.category).distinct().all()
    categories = [cat[0] for cat in categories]
    
    # Get unique locations for filter
    locations = db.session.query(Listing.location).distinct().all()
    locations = [loc[0] for loc in locations]
    
    return render_template(
        'index.html',
        listings=listings,
        categories=categories,
        locations=locations,
        current_category=category,
        search=search,
        location=location
    )

@app.route('/post', methods=['GET', 'POST'])
def post_listing():
    """Post a new listing"""
    if request.method == 'POST':
        # Get form data
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        price = float(request.form.get('price', 0) or 0)
        category = request.form.get('category', '').strip()
        location = request.form.get('location', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        whatsapp = request.form.get('whatsapp', '').strip()
        
        # Validate
        if not all([title, description, price, category, location]):
            flash('Please fill in all required fields (Title, Description, Price, Category, Location)', 'error')
            return redirect(url_for('post_listing'))
        
        # Check if at least one contact method provided
        if not any([phone, email, whatsapp]):
            flash('Please provide at least one contact method (Phone, Email, or WhatsApp)', 'error')
            return redirect(url_for('post_listing'))
        
        # Handle image upload
        image_file = request.files.get('image')
        image_filename = None
        
        if image_file and allowed_file(image_file.filename):
            filename = secure_filename(image_file.filename)
            # Add timestamp to avoid name collisions
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            image_filename = f"{timestamp}_{filename}"
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], image_filename)
            image_file.save(image_path)
        
        # Create listing
        listing = Listing(
            title=title,
            description=description,
            price=price,
            category=category,
            location=location,
            phone=phone,
            email=email,
            whatsapp=whatsapp,
            image_filename=image_filename,
            admin_approved=False  # Require admin approval (or set to True for instant)
        )
        
        db.session.add(listing)
        db.session.commit()
        
        flash('Your listing has been submitted! It will appear after admin approval.', 'success')
        return redirect(url_for('index'))
    
    return render_template('post.html')

@app.route('/item/<int:listing_id>')
def view_item(listing_id):
    """View a single listing"""
    listing = Listing.query.get_or_404(listing_id)
    
    if not listing.is_active or not listing.admin_approved:
        abort(404)
    
    return render_template('item.html', listing=listing)

@app.route('/report/<int:listing_id>', methods=['POST'])
def report_listing(listing_id):
    """Report a listing (spam/inappropriate)"""
    listing = Listing.query.get_or_404(listing_id)
    listing.is_reported = True
    db.session.commit()
    flash('Thank you for reporting. We will review this listing.', 'info')
    return redirect(url_for('view_item', listing_id=listing_id))

@app.route('/about')
def about():
    """About page"""
    return render_template('about.html')

@app.route('/privacy')
def privacy():
    """Privacy policy"""
    return render_template('privacy.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Admin login page"""
    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == os.getenv('ADMIN_PASSWORD', 'admin123'):
            session['admin_logged_in'] = True
            flash('Welcome back, Admin!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            error = 'Invalid password. Please try again.'
    
    return render_template('admin_login.html', error=error)

@app.route('/admin/logout')
def admin_logout():
    """Admin logout"""
    session.pop('admin_logged_in', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

# ============================================
# ADMIN ROUTES (Simple protection)
# ============================================

@app.route('/admin')
@admin_required
def admin_dashboard():
    """Simple admin dashboard - protect with basic auth or environment variable"""
    # In production, use proper authentication
    # This is a simple implementation for demo
    pending_listings = Listing.query.filter_by(admin_approved=False, is_active=True).all()
    active_listings = Listing.query.filter_by(admin_approved=True, is_active=True).all()
    reported_listings = Listing.query.filter_by(is_reported=True).all()
    
    return render_template(
        'admin.html',
        pending=pending_listings,
        active=active_listings,
        reported=reported_listings
    )

@app.route('/admin/approve/<int:listing_id>')
@admin_required
def approve_listing(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    listing.admin_approved = True
    db.session.commit()
    flash('Listing approved!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete/<int:listing_id>')
@admin_required
def delete_listing(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    listing.is_active = False
    db.session.commit()
    flash('Listing deleted.', 'info')
    return redirect(url_for('admin_dashboard'))

# ============================================
# INITIALIZE DATABASE
# ============================================

with app.app_context():
    db.create_all()
    print("Database initialized!")

# ============================================
# RUN THE APP
# ============================================

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)