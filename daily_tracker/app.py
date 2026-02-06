from flask import Flask, render_template, request, redirect, session, flash
from datetime import datetime, date
import sqlite3

app = Flask(__name__, template_folder="templates")
app.secret_key = "daily_tracker_secret"

DB_NAME = "daily_tracker.db"

# ------------------ DATABASE HELPERS ------------------
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def column_exists(table, column):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    exists = any(row["name"] == column for row in cur.fetchall())
    conn.close()
    return exists

def init_db():
    conn = get_db()
    cur = conn.cursor()

    # ---------------- USERS ----------------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        reset_requested INTEGER DEFAULT 0
    )
    """)

    # ---------------- ACTIVITIES ----------------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        activity_date TEXT,
        clock_in TEXT,
        activity_name TEXT,
        start_time TEXT,
        end_time TEXT,
        duration INTEGER,
        clock_out TEXT
    )
    """)

    # 🔑 IMPORTANT: Index for fast replacement check
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_activity_unique
    ON activities(username, activity_date, start_time, end_time)
    """)

    conn.commit()
    conn.close()

init_db()

# ------------------ WELCOME PAGE ------------------
@app.route("/")
def welcome():
    return render_template("welcome.html")

# ------------------ EMPLOYEE LOGIN ------------------
@app.route("/employee", methods=["GET", "POST"])
def employee_login():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT username, password, reset_requested FROM users")
    users = {
        row["username"]: {
            "password": row["password"],
            "reset_requested": row["reset_requested"]
        }
        for row in cur.fetchall()
    }
    conn.close()

    # Step 1: Username selection
    if request.method == "POST" and "username" in request.form and "password" not in request.form:
        username = request.form.get("username")
        session["temp_user"] = username

        if username in users:
            if users[username]["reset_requested"] == 1:
                return render_template("index.html", step="pending")

            if users[username]["reset_requested"] == 2:
                return render_template("index.html", step="create")

            return render_template("index.html", step="password")

        else:
            return render_template("index.html", step="create")

    # Step 2: Password create/login/reset
    if request.method == "POST" and "password" in request.form:
        username = session.get("temp_user")
        password = request.form.get("password")

        # New user
        if username not in users:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, password)
            )
            conn.commit()
            conn.close()

            session["username"] = username
            session.pop("temp_user")
            return redirect("/dashboard")

        # Reset approved
        if users[username]["reset_requested"] == 2:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                UPDATE users
                SET password = ?, reset_requested = 0
                WHERE username = ?
            """, (password, username))
            conn.commit()
            conn.close()

            session["username"] = username
            session.pop("temp_user")
            return redirect("/dashboard")

        # Normal login
        if users[username]["password"] == password:
            session["username"] = username
            session.pop("temp_user")
            return redirect("/dashboard")

        flash("Wrong password")
        return render_template("index.html", step="password")

    return render_template("index.html")

# ------------------ PASSWORD RESET REQUEST ------------------
@app.route("/request-reset", methods=["POST"])
def request_reset():
    username = session.get("temp_user")

    if not username:
        return "", 403

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE users
        SET reset_requested = 1
        WHERE username = ?
    """, (username,))
    conn.commit()
    conn.close()

    flash("Reset request sent to manager")
    return "", 204

# ------------------ MANAGER RESET REQUESTS ------------------
@app.route("/manager/reset-requests")
def manager_reset_requests():
    if not session.get("manager"):
        return redirect("/manager")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT username
        FROM users
        WHERE reset_requested = 1
    """)
    requests = cur.fetchall()
    conn.close()

    return render_template("manager_reset_requests.html", requests=requests)

# ------------------ MANAGER APPROVES RESET ------------------
@app.route("/manager/approve-reset", methods=["POST"])
def manager_approve_reset():
    if not session.get("manager"):
        return redirect("/manager")

    username = request.form["username"]

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE users
        SET reset_requested = 2,
            password = NULL
        WHERE username = ?
    """, (username,))
    conn.commit()
    conn.close()

    return redirect("/manager/reset-requests")

# ------------------ MANAGER LOGIN ------------------
@app.route("/manager", methods=["GET", "POST"])
def manager_login():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT username, password FROM users")
    users = {row["username"]: row["password"] for row in cur.fetchall()}
    conn.close()

    if request.method == "POST" and "manager_name" in request.form and "password" not in request.form:
        manager_name = request.form.get("manager_name")
        username = f"manager_{manager_name}"
        session["temp_manager"] = username

        if username in users:
            return render_template("manager_login.html", step="password")
        return render_template("manager_login.html", step="create")

    if request.method == "POST" and "password" in request.form:
        username = session.get("temp_manager")
        password = request.form.get("password")

        if username not in users:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, password)
            )
            conn.commit()
            conn.close()

            session["manager"] = username
            session.pop("temp_manager")
            return redirect("/manager/dashboard")

        if users[username] == password:
            session["manager"] = username
            session.pop("temp_manager")
            return redirect("/manager/dashboard")

        flash("Wrong password")
        return render_template("manager_login.html", step="password")

    return render_template("manager_login.html")

# ------------------ DASHBOARD ------------------
@app.route("/dashboard")
def dashboard():
    if "username" not in session:
        return redirect("/employee")
    return render_template("dashboard.html", name=session["username"])

# ------------------ ACTIVITY ------------------
@app.route("/activity", methods=["GET", "POST"])
def activity():
    if "username" not in session:
        return redirect("/employee")

    username = session["username"]

    if request.method == "POST":
        activity_date = request.form.get("activity_date")
        clock_in = request.form.get("clock_in")
        clock_out = request.form.get("clock_out")

        activity_names = request.form.getlist("activity_name[]")
        start_times = request.form.getlist("start_time[]")
        end_times = request.form.getlist("end_time[]")

        conn = get_db()
        cur = conn.cursor()

        for i in range(len(activity_names)):
            start = datetime.strptime(start_times[i], "%H:%M")
            end = datetime.strptime(end_times[i], "%H:%M")

            # ⛔ Safety check
            if end <= start:
                flash("End time must be after start time")
                return redirect("/activity")

            duration = int((end - start).total_seconds() / 60)

            # 🔁 DELETE SAME DATE + SAME TIME SLOT (REPLACE LOGIC)
            cur.execute("""
                DELETE FROM activities
                WHERE username = ?
                AND activity_date = ?
                AND start_time = ?
                AND end_time = ?
            """, (
                username,
                activity_date,
                start_times[i],
                end_times[i]
            ))

            # ✅ INSERT FRESH ENTRY
            cur.execute("""
                INSERT INTO activities (
                    username, activity_date, clock_in,
                    activity_name, start_time, end_time,
                    duration, clock_out
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                username,
                activity_date,
                clock_in,
                activity_names[i],
                start_times[i],
                end_times[i],
                duration,
                clock_out
            ))

        conn.commit()
        conn.close()

        return redirect("/success")

    return render_template(
        "activity.html",
        selected=username,
        max_date=date.today().isoformat()
    )


# ------------------ SUCCESS ------------------
@app.route("/success")
def success():
    if "username" not in session:
        return redirect("/employee")
    return render_template("success.html")

# ------------------ LOGOUT ------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ------------------ MANAGER DASHBOARD ------------------
@app.route("/manager/dashboard")
def manager_dashboard():
    if "manager" not in session:
        return redirect("/manager")

    # ---- Month & Year Filter ----
    selected_month = request.args.get("month")
    selected_year = request.args.get("year")

    today = date.today()

    if not selected_month:
        selected_month = f"{today.month:02d}"
    else:
        selected_month = selected_month.zfill(2)

    if not selected_year:
        selected_year = str(today.year)

    conn = get_db()
    cur = conn.cursor()

    # ---- Build YEAR LIST dynamically from DB ----
    cur.execute("""
        SELECT DISTINCT strftime('%Y', activity_date) AS year
        FROM activities
        ORDER BY year DESC
    """)
    years = [row["year"] for row in cur.fetchall()]

    # fallback if DB is empty
    if not years:
        years = [str(today.year)]

    # ---- Pending Reset Requests Count ----
    cur.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE reset_requested = 1
    """)
    pending_count = cur.fetchone()[0]

    # ---- Activity Data (Filtered by Month & Year) ----
    cur.execute("""
        SELECT username, activity_date, duration
        FROM activities
        WHERE strftime('%m', activity_date) = ?
          AND strftime('%Y', activity_date) = ?
    """, (selected_month, selected_year))

    rows = cur.fetchall()
    conn.close()

    # ---- Process Employee Data ----
    employee_data = {}

    for row in rows:
        if row["username"].startswith("manager_"):
            continue

        if row["username"] not in employee_data:
            employee_data[row["username"]] = {
                "total_minutes": 0,
                "days": set()
            }

        employee_data[row["username"]]["total_minutes"] += row["duration"]
        employee_data[row["username"]]["days"].add(row["activity_date"])

    data = []
    for username, info in employee_data.items():
        productive_hours = info["total_minutes"] // 60
        days = len(info["days"])
        available_hours = days * 7
        ideal_hours = max(available_hours - productive_hours, 0)
        productivity = (
            productive_hours / available_hours * 100
            if available_hours > 0 else 0
        )

        data.append({
            "name": username,
            "productive": productive_hours,
            "days": days,
            "available": available_hours,
            "ideal": ideal_hours,
            "productivity": round(productivity, 2)
        })

    return render_template(
        "manager_dashboard.html",
        data=data,
        pending_count=pending_count,
        selected_month=selected_month,
        selected_year=selected_year,
        years=years   # ✅ THIS WAS MISSING
    )
# ------------------ MANAGER EMPLOYEE DETAIL ------------------
@app.route("/manager/employee/<username>")
def manager_employee_detail(username):
    if "manager" not in session:
        return redirect("/manager")

    selected_month = request.args.get("month")
    selected_year = request.args.get("year")

    today = date.today()
    if not selected_month:
        selected_month = f"{today.month:02d}"
    if not selected_year:
        selected_year = str(today.year)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT activity_date, activity_name, start_time, end_time
        FROM activities
        WHERE username = ?
          AND strftime('%m', activity_date) = ?
          AND strftime('%Y', activity_date) = ?
        ORDER BY activity_date, start_time
    """, (username, selected_month, selected_year))

    rows = cur.fetchall()
    conn.close()

    # ---- Group by date ----
    grouped = {}
    for r in rows:
        date_key = r["activity_date"]
        grouped.setdefault(date_key, []).append({
            "activity": r["activity_name"],
            "start": r["start_time"],
            "end": r["end_time"]
        })

    return render_template(
        "manager_employee_report.html",
        username=username,
        grouped=grouped,
        selected_month=selected_month,
        selected_year=selected_year
    )


# ------------------ REPORT ------------------
@app.route("/report")
def report():
    if "username" not in session:
        return redirect("/employee")

    username = session["username"]

    selected_month = request.args.get("month")
    selected_year = request.args.get("year")
    selected_day = request.args.get("day")  # 👈 NEW

    today = date.today()
    if not selected_month:
        selected_month = f"{today.month:02d}"
    if not selected_year:
        selected_year = str(today.year)

    conn = get_db()
    cur = conn.cursor()

    # --- fetch all activities for user ---
    cur.execute("""
        SELECT activity_date, activity_name, start_time, end_time, duration
        FROM activities
        WHERE username = ?
    """, (username,))
    rows = cur.fetchall()

    daily_minutes = {}
    available_years = set()

    for row in rows:
        try:
            d = datetime.strptime(row["activity_date"], "%Y-%m-%d")
        except:
            continue

        available_years.add(d.year)

        if d.month == int(selected_month) and d.year == int(selected_year):
            daily_minutes.setdefault(row["activity_date"], 0)
            daily_minutes[row["activity_date"]] += row["duration"]

    # --- monthly table ---
    report_data = []
    total_minutes = 0

    for d, mins in sorted(daily_minutes.items()):
        hrs = mins // 60
        rem = mins % 60
        report_data.append({
            "date": d,
            "time": f"{hrs} hours {rem} min"
        })
        total_minutes += mins

    # --- cards ---
    productive_hours = total_minutes / 60
    working_days = len(daily_minutes)
    available_hours = working_days * 7
    idle_hours = max(available_hours - productive_hours, 0)
    productivity = (
        productive_hours / available_hours * 100
        if available_hours > 0 else 0
    )

    cards = {
        "productive": f"{int(productive_hours)} hrs {int((productive_hours % 1) * 60)} min",
        "working_days": working_days,
        "available": f"{available_hours} hrs",
        "idle": f"{int(idle_hours)} hrs {int((idle_hours % 1) * 60)} min",
        "productivity": f"{productivity:.2f}%"
    }

    # --- 🔍 selected day activities ---
    day_activities = []
    if selected_day:
        cur.execute("""
            SELECT activity_name, start_time, end_time, duration
            FROM activities
            WHERE username = ?
              AND activity_date = ?
            ORDER BY start_time
        """, (username, selected_day))
        day_activities = cur.fetchall()

    conn.close()

    return render_template(
        "report.html",
        data=report_data,
        cards=cards,
        name=username,
        selected_month=selected_month,
        selected_year=selected_year,
        selected_day=selected_day,          # 👈 NEW
        day_activities=day_activities,      # 👈 NEW
        years=sorted(available_years)
    )


# ------------------ RUN APP ------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
