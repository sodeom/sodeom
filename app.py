import hashlib
import mimetypes
import os
import re
from datetime import datetime
from urllib.parse import quote_plus

import dotenv
import requests
import stripe
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
)
from flask_sqlalchemy import SQLAlchemy
from openai import OpenAI

# Load environment variables FIRST
dotenv.load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "replace-this-in-production")

# Stripe Configuration - All from environment variables
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
MONTHLY_PRICE_ID = os.getenv("STRIPE_PRO_MONTHLY_PRICE_ID", "")
LIFETIME_PRICE_ID = os.getenv("STRIPE_PRO_LIFETIME_PRICE_ID", "")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# AI features enabled via GitHub Models API
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_ENDPOINT = "https://models.github.ai/inference"
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gpt-4o-mini")
client = OpenAI(base_url=GITHUB_ENDPOINT, api_key=GITHUB_TOKEN)

# Import user database functions
from userdb import create_user, get_user, get_user_by_id, set_pro, set_pro_by_id

# Initialize SQLAlchemy
db = SQLAlchemy(app)


class Metrics(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, unique=True)
    total_searches = db.Column(db.Integer, default=0)
    total_ai_summaries = db.Column(db.Integer, default=0)
    ai_limit_hits = db.Column(db.Integer, default=0)
    upgrade_clicks = db.Column(db.Integer, default=0)
    successful_upgrades = db.Column(db.Integer, default=0)


def get_today_metrics():
    today = datetime.utcnow().date()
    metrics = Metrics.query.filter_by(date=today).first()
    if not metrics:
        metrics = Metrics(date=today)
        db.session.add(metrics)
        db.session.commit()
    return metrics


# ============================================================================
# STRIPE PAYMENT ROUTES
# ============================================================================
FOUNDING_MEMBER_LIMIT = 100


@app.route("/founding-member-count")
def founding_member_count():
    from userdb import get_all_pro_users

    # Count lifetime members
    with get_db() as db:
        cur = db.execute(
            "SELECT COUNT(*) FROM users WHERE subscription_type = 'lifetime'"
        )
        count = cur.fetchone()[0]
    spots_remaining = FOUNDING_MEMBER_LIMIT - count
    return jsonify({"spots_remaining": spots_remaining, "limit": FOUNDING_MEMBER_LIMIT})


@app.route("/upgrade")
def upgrade_page():
    spots_remaining = FOUNDING_MEMBER_LIMIT
    with get_db() as db:
        cur = db.execute(
            "SELECT COUNT(*) FROM users WHERE subscription_type = 'lifetime'"
        )
        count = cur.fetchone()[0]
        spots_remaining = FOUNDING_MEMBER_LIMIT - count
    return render_template(
        "upgrade.html",
        stripe_publishable_key=STRIPE_PUBLISHABLE_KEY,
        spots_remaining=spots_remaining,
    )


@app.route("/create-checkout-session", methods=["POST"])
def create_checkout():
    """Create a Stripe checkout session for payment."""
    data = request.get_json() or {}
    price_type = data.get("type", "lifetime")  # "monthly" or "lifetime"

    # Get user email from request (for now, we'll use email-based identification)
    # In production, this would come from session/auth
    email = data.get("email")

    if not email:
        return jsonify({"error": "Email required"}), 400

    if price_type == "monthly":
        price_id = MONTHLY_PRICE_ID
        mode = "subscription"
    else:
        price_id = LIFETIME_PRICE_ID
        mode = "payment"

    if not price_id:
        return jsonify({"error": "Price not configured"}), 500

    # Create or get user
    user = create_user(email)

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            mode=mode,
            success_url=request.host_url + "success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=request.host_url + "cancel",
            metadata={"user_id": user["id"], "email": email, "price_type": price_type},
            customer_email=email,
        )
        return jsonify({"id": session.id})
    except Exception as e:
        print(f"Stripe error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    """Handle Stripe webhook events for payment completion."""
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    if not STRIPE_WEBHOOK_SECRET:
        print("WARNING: STRIPE_WEBHOOK_SECRET not configured")
        return "Webhook secret not configured", 500

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        print(f"Invalid payload: {e}")
        return "Invalid payload", 400
    except stripe.error.SignatureVerificationError as e:
        print(f"Invalid signature: {e}")
        return "Invalid signature", 400

    # Handle the event
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        user_id = session["metadata"].get("user_id")
        email = session["metadata"].get("email")
        price_type = session["metadata"].get("price_type")
        mode = session.get("mode")
        customer_id = session.get("customer")
        subscription_id = session.get("subscription")

        print(f"Payment completed for user {user_id} ({email}) - {price_type}")

        # Activate Pro status and store Stripe info
        if mode == "payment":
            # Lifetime
            if email:
                set_pro(email)
                update_stripe_info(
                    email, customer_id=customer_id, subscription_status="lifetime"
                )
        else:
            # Monthly subscription
            if email:
                set_pro(email)
                update_stripe_info(
                    email,
                    customer_id=customer_id,
                    subscription_id=subscription_id,
                    subscription_status="active",
                )

        print(f"User {email} is now Pro!")

        metrics = get_today_metrics()
        metrics.successful_upgrades += 1
        db.session.commit()

    elif event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        subscription_id = subscription["id"]
        user = None
        with get_db() as db:
            cur = db.execute(
                "SELECT * FROM users WHERE subscription_id = ?", (subscription_id,)
            )
            user = cur.fetchone()
        if user:
            expire_pro(user["email"])
            update_stripe_info(user["email"], subscription_status="canceled")
            print(f"User {user['email']} subscription canceled.")

    elif event["type"] == "invoice.payment_failed":
        invoice = event["data"]["object"]
        subscription_id = invoice.get("subscription")
        user = None
        with get_db() as db:
            cur = db.execute(
                "SELECT * FROM users WHERE subscription_id = ?", (subscription_id,)
            )
            user = cur.fetchone()
        if user:
            expire_pro(user["email"])
            update_stripe_info(user["email"], subscription_status="past_due")
            print(f"User {user['email']} payment failed.")

    elif event["type"] == "customer.subscription.updated":
        subscription = event["data"]["object"]
        subscription_id = subscription["id"]
        status = subscription["status"]
        user = None
        with get_db() as db:
            cur = db.execute(
                "SELECT * FROM users WHERE subscription_id = ?", (subscription_id,)
            )
            user = cur.fetchone()
        if user:
            update_stripe_info(user["email"], subscription_status=status)
            print(f"User {user['email']} subscription updated: {status}")

    return "", 200


@app.route("/success")
def success():
    """Render the success page after payment."""
    session_id = request.args.get("session_id")
    return render_template("success.html", session_id=session_id)


@app.route("/cancel")
def cancel():
    """Render the cancellation page if payment was cancelled."""
    return render_template("cancel.html")


@app.route("/check-pro/<email>")
def check_pro(email):
    """Check if a user has Pro status."""
    user = get_user(email)
    if user:
        return jsonify(
            {
                "email": email,
                "is_pro": has_active_pro(user),
                "subscription_status": user.get("subscription_status", ""),
            }
        )
    return jsonify({"error": "User not found"}), 404


@app.route("/upgrade-test", methods=["POST"])
def upgrade_test():
    """Test endpoint to upgrade a user without payment (for testing)."""
    email = request.json.get("email")
    if not email:
        return jsonify({"error": "Email required"}), 400

    user = create_user(email)
    set_pro(email)
    return jsonify({"message": f"User {email} is now Pro (Test Mode)", "pro": True})


# ============================================================================
# IMAGE SEARCH UTILITIES
# ============================================================================
