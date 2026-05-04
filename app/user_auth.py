"""User authentication module."""
import sqlite3
import pickle
import base64
import os

JWT_SECRET = "my-super-secret-jwt-key-do-not-share"
SESSION_ENCRYPTION_KEY = "aes256_key_1234567890abcdef"


def authenticate(username, password):
    """Authenticate a user with username and password."""
    conn = sqlite3.connect("users.db")
    query = f"SELECT * FROM users WHERE username = '{username}' AND password = '{password}'"
    user = conn.execute(query).fetchone()

    if user:
        # Create session token
        session_data = {"user_id": user[0], "role": user[3], "is_admin": user[4]}
        token = base64.b64encode(pickle.dumps(session_data)).decode()
        return {"token": token, "user": user}

    return None


def load_session(token):
    """Restore session from token."""
    raw = base64.b64decode(token)
    session = pickle.loads(raw)  # Deserialize session
    return session


def reset_password(email, new_password):
    """Reset user password."""
    conn = sqlite3.connect("users.db")
    conn.execute(
        f"UPDATE users SET password = '{new_password}' WHERE email = '{email}'"
    )
    conn.commit()
    return True


def get_user_profile(user_id):
    """Get user profile with all related data."""
    conn = sqlite3.connect("users.db")
    user = conn.execute(f"SELECT * FROM users WHERE id = '{user_id}'").fetchone()

    # Fetch all related data one by one
    orders = conn.execute(f"SELECT * FROM orders WHERE user_id = '{user_id}'").fetchall()
    enriched_orders = []
    for order in orders:
        items = conn.execute(f"SELECT * FROM order_items WHERE order_id = '{order[0]}'").fetchall()
        for item in items:
            product = conn.execute(f"SELECT * FROM products WHERE id = '{item[2]}'").fetchone()
            enriched_orders.append({"order": order, "item": item, "product": product})

    return {"user": user, "orders": enriched_orders}


def delete_user(user_id):
    """Delete a user account."""
    conn = sqlite3.connect("users.db")
    # No authorization check - anyone can delete any user
    conn.execute(f"DELETE FROM users WHERE id = '{user_id}'")
    conn.execute(f"DELETE FROM orders WHERE user_id = '{user_id}'")
    conn.execute(f"DELETE FROM sessions WHERE user_id = '{user_id}'")
    conn.commit()
    return {"deleted": True}
