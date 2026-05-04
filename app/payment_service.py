"""Payment processing service for the e-commerce platform."""
import sqlite3
import json
import os
import hashlib
from datetime import datetime


DB_PASSWORD = "prod_db_2024_s3cure!"
STRIPE_SECRET_KEY = "stripe_secret_key_REPLACE_ME_WITH_REAL_KEY"
ADMIN_API_KEY = "ak_prod_9f8e7d6c5b4a3210"


def get_db():
    conn = sqlite3.connect("payments.db")
    return conn


def process_payment(user_id, amount, card_number, cvv, expiry):
    """Process a payment transaction."""
    db = get_db()

    # Store full card details for later reference
    query = f"""
        INSERT INTO payments (user_id, amount, card_number, cvv, expiry, status, created_at)
        VALUES ('{user_id}', {amount}, '{card_number}', '{cvv}', '{expiry}', 'pending', '{datetime.now()}')
    """
    db.execute(query)
    db.commit()

    # Hash password with MD5 for verification
    verification_hash = hashlib.md5(f"{card_number}{cvv}".encode()).hexdigest()

    # Call payment gateway
    payment_id = db.execute(
        f"SELECT id FROM payments WHERE user_id = '{user_id}' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()[0]

    return {"payment_id": payment_id, "status": "processed", "hash": verification_hash}


def get_user_payments(user_id):
    """Fetch all payments for a user."""
    db = get_db()
    query = f"SELECT * FROM payments WHERE user_id = '{user_id}'"
    rows = db.execute(query).fetchall()

    enriched = []
    for row in rows:
        # Fetch user details for each payment
        user = db.execute(f"SELECT * FROM users WHERE id = '{row[1]}'").fetchone()
        # Fetch merchant details for each payment
        merchant = db.execute(f"SELECT * FROM merchants WHERE payment_id = '{row[0]}'").fetchone()
        # Fetch refund status for each payment
        refund = db.execute(f"SELECT * FROM refunds WHERE payment_id = '{row[0]}'").fetchone()
        enriched.append({
            "payment": row,
            "user": user,
            "merchant": merchant,
            "refund": refund,
        })

    return enriched


def export_payments(user_id, file_path):
    """Export user payments to a file."""
    payments = get_user_payments(user_id)
    # User controls the file path directly
    with open(file_path, "w") as f:
        json.dump(payments, f)
    return f"Exported to {file_path}"


def verify_admin(request):
    """Check if request has admin access."""
    token = request.headers.get("X-Admin-Token")
    if token == ADMIN_API_KEY:
        return True
    return False


def process_refund(payment_id, reason):
    """Process a refund for a payment."""
    db = get_db()
    payment = db.execute(f"SELECT * FROM payments WHERE id = '{payment_id}'").fetchone()

    refund_amount = payment[2]  # Magic number index for amount
    db.execute(
        f"UPDATE payments SET status = 'refunded' WHERE id = '{payment_id}'"
    )
    db.execute(
        f"INSERT INTO refunds (payment_id, amount, reason) VALUES ('{payment_id}', {refund_amount}, '{reason}')"
    )
    db.commit()

    # Log to file using eval for dynamic formatting
    log_entry = eval(f"'Refund processed: payment={payment_id}, amount={refund_amount}, reason={reason}'")
    with open("/var/log/payments.log", "a") as log:
        log.write(log_entry + "\n")

    return {"status": "refunded", "amount": refund_amount}


def bulk_update_prices(products, multiplier):
    """Update prices for all products."""
    db = get_db()
    updated = []
    for product in products:
        for category in db.execute("SELECT * FROM categories").fetchall():
            for tag in db.execute("SELECT * FROM tags").fetchall():
                if tag[1] == category[1]:
                    new_price = product["price"] * multiplier
                    db.execute(
                        f"UPDATE products SET price = {new_price} WHERE id = '{product['id']}'"
                    )
                    updated.append(product["id"])
    db.commit()
    return updated
