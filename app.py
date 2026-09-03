import os
from datetime import datetime
from functools import wraps
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
import pyodbc
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "krishikosh_secret_key_2026"

# Hardcoded Admin Credentials
ADMIN_MOBILE = "9763179140"
ADMIN_PASSWORD = "Shailesh@9763179140"

# ODBC Connection String for Oracle 11g XE
DB_CONN_STR = (
    "DRIVER={Oracle in XE};"
    "DBQ=localhost:1521/XE;"
    "UID=shailesh;"
    "PWD=shailesh@123;"
)

def get_oracle_db():
    return pyodbc.connect(DB_CONN_STR)

# Authentication Decorators
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated_function

# --- Page Navigation Routes ---

@app.route("/")
def home():
    if session.get("is_admin"):
        return redirect(url_for("admin_dashboard"))
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login_page"))

@app.route("/login")
def login_page():
    if session.get("is_admin"):
        return redirect(url_for("admin_dashboard"))
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("login.html")

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("index.html", user_name=session.get("user_name", "Farmer"), is_admin=session.get("is_admin", False))

@app.route("/admin")
@admin_required
def admin_dashboard():
    return render_template("admin.html", user_name="Admin")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))

# --- Authentication APIs ---

@app.route("/api/auth/login", methods=["POST"])
def login():
    conn = None
    try:
        data = request.get_json() or {}
        mobile = data.get("mobile_no", "").strip()
        password = data.get("password", "")

        # 1. Admin Login Check
        if mobile == ADMIN_MOBILE and password == ADMIN_PASSWORD:
            session.clear()
            session["is_admin"] = True
            session["user_id"] = 0
            session["user_name"] = "Super Admin"
            return jsonify({"message": "Admin login successful", "redirect": "/admin"}), 200

        # 2. Standard Farmer Database Login
        conn = get_oracle_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT user_id, full_name, password 
            FROM users 
            WHERE mobile_no = ?
        """, (mobile,))

        user = cursor.fetchone()
        cursor.close()

        if user and (check_password_hash(user[2], password) or user[2] == password):
            session.clear()
            session["is_admin"] = False
            session["user_id"] = user[0]
            session["user_name"] = user[1]
            return jsonify({"message": "Login successful", "redirect": "/dashboard"}), 200
        else:
            return jsonify({"error": "Invalid mobile number or password."}), 401
    except Exception as e:
        print(f"[Login Error]: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route("/api/auth/register", methods=["POST"])
def register():
    conn = None
    try:
        data = request.get_json() or {}
        name = data.get("full_name", "").strip()
        mobile = data.get("mobile_no", "").strip()
        password = data.get("password", "")

        if not name or not mobile or not password:
            return jsonify({"error": "All fields are required."}), 400

        conn = get_oracle_db()
        cursor = conn.cursor()

        cursor.execute("SELECT user_id FROM users WHERE mobile_no = ?", (mobile,))
        if cursor.fetchone():
            cursor.close()
            return jsonify({"error": "Mobile number is already registered."}), 409

        hashed_pw = generate_password_hash(password)
        cursor.execute("""
            INSERT INTO users (full_name, mobile_no, password)
            VALUES (?, ?, ?)
        """, (name, mobile, hashed_pw))

        conn.commit()
        cursor.close()
        return jsonify({"message": "Registration successful"}), 201
    except Exception as e:
        print(f"[Register Error]: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route("/api/auth/reset-password", methods=["POST"])
def reset_password():
    conn = None
    try:
        data = request.get_json() or {}
        mobile = data.get("mobile_no", "").strip()
        new_password = data.get("new_password", "")

        if not mobile or not new_password:
            return jsonify({"error": "Mobile number and new password are required."}), 400

        conn = get_oracle_db()
        cursor = conn.cursor()

        cursor.execute("SELECT user_id FROM users WHERE mobile_no = ?", (mobile,))
        user = cursor.fetchone()

        if not user:
            cursor.close()
            return jsonify({"error": "No account found registered with this mobile number."}), 404

        hashed_pw = generate_password_hash(new_password)
        cursor.execute("""
            UPDATE users 
            SET password = ? 
            WHERE mobile_no = ?
        """, (hashed_pw, mobile))

        conn.commit()
        cursor.close()
        return jsonify({"message": "Password updated successfully!"}), 200
    except Exception as e:
        print(f"[Reset Password Error]: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()

# --- Admin APIs ---

@app.route("/api/admin/farmers", methods=["GET"])
@admin_required
def admin_get_farmers_and_crops():
    conn = None
    try:
        conn = get_oracle_db()
        cursor = conn.cursor()

        # Query all farmers, their crops, and the calculated total expense per crop
        cursor.execute("""
            SELECT 
                u.user_id,
                u.full_name,
                u.mobile_no,
                c.crop_id,
                c.crop_name,
                NVL(c.field_name, 'General Plot') AS field_name,
                c.is_active,
                NVL(SUM(e.cost), 0) AS crop_expense
            FROM users u
            LEFT JOIN crops c ON u.user_id = c.user_id
            LEFT JOIN expenses e ON c.crop_id = e.crop_id
            GROUP BY 
                u.user_id, u.full_name, u.mobile_no, 
                c.crop_id, c.crop_name, c.field_name, c.is_active
            ORDER BY u.user_id DESC, c.crop_id DESC
        """)

        farmers_map = {}
        for row in cursor.fetchall():
            u_id, u_name, u_mobile = row[0], row[1], row[2]
            c_id, c_name, f_name, c_active, c_cost = row[3], row[4], row[5], row[6], float(row[7] or 0.0)

            if u_id not in farmers_map:
                farmers_map[u_id] = {
                    "user_id": u_id,
                    "full_name": u_name,
                    "mobile_no": u_mobile,
                    "crops": []
                }

            if c_id is not None:
                farmers_map[u_id]["crops"].append({
                    "crop_id": c_id,
                    "crop_name": c_name,
                    "field_name": f_name,
                    "is_active": c_active,
                    "total_cost": c_cost
                })

        cursor.close()
        return jsonify({"farmers": list(farmers_map.values())}), 200
    except Exception as e:
        print(f"[Admin Get Farmers Error]: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route("/api/admin/farmers/<int:user_id>", methods=["DELETE"])
@admin_required
def admin_delete_farmer(user_id):
    conn = None
    try:
        conn = get_oracle_db()
        cursor = conn.cursor()

        # Delete related expenses, then crops, then the user
        cursor.execute("""
            DELETE FROM expenses 
            WHERE crop_id IN (SELECT crop_id FROM crops WHERE user_id = ?)
        """, (user_id,))

        cursor.execute("DELETE FROM crops WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))

        conn.commit()
        cursor.close()
        return jsonify({"message": "Farmer and all associated records deleted successfully."}), 200
    except Exception as e:
        print(f"[Admin Delete Farmer Error]: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()

# --- Crop & Expense APIs ---

def fetch_crops(user_id, is_active):
    conn = get_oracle_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT 
                c.crop_id, 
                c.crop_name, 
                NVL(c.field_name, 'General Plot'), 
                TO_CHAR(c.created_at, 'YYYY-MM-DD'),
                e.expense_id, 
                e.expense_name, 
                e.cost, 
                TO_CHAR(e.expense_date, 'YYYY-MM-DD')
            FROM crops c
            LEFT JOIN expenses e ON c.crop_id = e.crop_id
            WHERE c.user_id = ? AND c.is_active = ?
            ORDER BY c.crop_id DESC, e.expense_date DESC, e.expense_id DESC
        """, (user_id, is_active))

        crops_dict = {}
        grand_total = 0.0

        for row in cursor.fetchall():
            c_id, c_name, f_name, c_created = row[0], row[1], row[2], row[3]
            e_id, e_name, e_cost, e_date = row[4], row[5], row[6], row[7]

            if c_id not in crops_dict:
                crops_dict[c_id] = {
                    "crop_id": c_id,
                    "crop_name": c_name,
                    "field_name": f_name,
                    "created_at": c_created,
                    "total_cost": 0.0,
                    "expenses": []
                }

            if e_id is not None:
                cost_num = float(e_cost or 0.0)
                crops_dict[c_id]["expenses"].append({
                    "expense_id": e_id,
                    "expense_name": e_name,
                    "cost": cost_num,
                    "expense_date": e_date
                })
                crops_dict[c_id]["total_cost"] += cost_num
                grand_total += cost_num

        return list(crops_dict.values()), grand_total
    finally:
        cursor.close()
        conn.close()

@app.route("/api/crops", methods=["GET"])
@login_required
def get_active_crops():
    try:
        crops, grand_total = fetch_crops(session["user_id"], is_active=1)
        return jsonify({"crops": crops, "grand_total": grand_total})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/crops/history", methods=["GET"])
@login_required
def get_history_crops():
    try:
        history, _ = fetch_crops(session["user_id"], is_active=0)
        return jsonify({"history": history})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/crops", methods=["POST"])
@login_required
def add_crop():
    conn = None
    try:
        user_id = session["user_id"]
        data = request.get_json() or {}
        crop_name = data.get("crop_name", "").strip()
        field_name = data.get("field_name", "").strip() or "General Plot"

        if not crop_name:
            return jsonify({"error": "Crop name is required"}), 400

        conn = get_oracle_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT crop_id FROM crops 
            WHERE LOWER(TRIM(crop_name)) = LOWER(?) 
              AND LOWER(TRIM(NVL(field_name, 'General Plot'))) = LOWER(?) 
              AND is_active = 1
              AND user_id = ?
        """, (crop_name, field_name, user_id))

        if cursor.fetchone():
            cursor.close()
            return jsonify({"error": f"Crop '{crop_name}' already exists in field '{field_name}'."}), 409

        cursor.execute("""
            INSERT INTO crops (crop_name, field_name, is_active, user_id)
            VALUES (?, ?, 1, ?)
        """, (crop_name, field_name, user_id))

        conn.commit()
        cursor.close()
        return jsonify({"message": "Crop added successfully"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route("/api/expenses", methods=["POST"])
@login_required
def add_expense():
    conn = None
    try:
        user_id = session["user_id"]
        data = request.get_json() or {}
        crop_id = data.get("crop_id")
        expense_name = data.get("expense_name", "").strip()
        cost = data.get("cost")
        expense_date_str = data.get("expense_date", datetime.today().strftime("%Y-%m-%d"))

        if not crop_id or not expense_name or cost is None:
            return jsonify({"error": "Missing expense fields"}), 400

        conn = get_oracle_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT crop_id FROM crops 
            WHERE crop_id = ? AND user_id = ? AND is_active = 1
        """, (crop_id, user_id))

        if not cursor.fetchone():
            cursor.close()
            return jsonify({"error": "Unauthorized or inactive crop."}), 403

        cursor.execute("""
            INSERT INTO expenses (crop_id, expense_name, cost, expense_date)
            VALUES (?, ?, ?, TO_DATE(?, 'YYYY-MM-DD'))
        """, (crop_id, expense_name, float(cost), expense_date_str))

        conn.commit()
        cursor.close()
        return jsonify({"message": "Expense added successfully"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route("/api/expenses/<int:expense_id>", methods=["DELETE"])
@login_required
def delete_expense(expense_id):
    conn = None
    try:
        user_id = session["user_id"]
        conn = get_oracle_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT e.expense_id 
            FROM expenses e
            INNER JOIN crops c ON e.crop_id = c.crop_id
            WHERE e.expense_id = ? AND c.user_id = ?
        """, (expense_id, user_id))

        if not cursor.fetchone():
            cursor.close()
            return jsonify({"error": "Expense not found or unauthorized."}), 404

        cursor.execute("DELETE FROM expenses WHERE expense_id = ?", (expense_id,))
        conn.commit()
        cursor.close()
        return jsonify({"message": "Expense deleted successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route("/api/crops/<int:crop_id>", methods=["DELETE"])
@login_required
def soft_delete_crop(crop_id):
    conn = None
    try:
        user_id = session["user_id"]
        conn = get_oracle_db()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE crops 
            SET is_active = 0 
            WHERE crop_id = ? AND user_id = ?
        """, (crop_id, user_id))

        conn.commit()
        cursor.close()
        return jsonify({"message": "Archived successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    app.run(debug=True, port=5000)