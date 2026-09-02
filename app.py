import os
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()
import google.generativeai as genai
from flask import jsonify

from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, login_required,
    logout_user, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash

basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
database_url = os.environ.get("DATABASE_URL")
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+pg8000://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url or (
    "sqlite:///" + os.path.join(basedir, "scheduler.db")
)
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to continue."
login_manager.login_message_category = "info"


# ---------------------------------------------------------------
# Models
# ---------------------------------------------------------------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    meetings = db.relationship(
        "Meeting", backref="owner", lazy=True, cascade="all, delete-orphan"
    )

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)


class Meeting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    title = db.Column(db.String(200), nullable=False)
    partner_branch = db.Column(db.String(200), nullable=False)
    meeting_type = db.Column(db.String(50), default="Video Call")
    meeting_date = db.Column(db.Date, nullable=False)
    meeting_time = db.Column(db.Time, nullable=True)

    attendees = db.Column(db.Text)          # name / email / role, one per line
    agenda = db.Column(db.Text)
    discussion_points = db.Column(db.Text)
    decisions = db.Column(db.Text)
    action_items = db.Column(db.Text)
    ideas = db.Column(db.Text)
    notes = db.Column(db.Text)

    priority = db.Column(db.String(20), default="Medium")
    status = db.Column(db.String(30), default="Scheduled")

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ---------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        error = None
        if not username or not email or not password:
            error = "All fields are required."
        elif password != confirm:
            error = "Passwords do not match."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif User.query.filter_by(username=username).first():
            error = "That username is already taken."
        elif User.query.filter_by(email=email).first():
            error = "An account with that email already exists."

        if error:
            flash(error, "error")
            return render_template("register.html", username=username, email=email)

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash("Account created. You can log in now.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter(
            (User.username == identifier) | (User.email == identifier.lower())
        ).first()

        if user and user.check_password(password):
            login_user(user)
            flash(f"Welcome back, {user.username}.", "success")
            next_page = request.args.get("next")
            return redirect(next_page or url_for("dashboard"))

        flash("Incorrect username/email or password.", "error")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# ---------------------------------------------------------------
# Scheduling routes (each user only sees their own meetings)
# ---------------------------------------------------------------
@app.route("/")
@login_required
def dashboard():
    status_filter = request.args.get("status", "")
    query = Meeting.query.filter_by(user_id=current_user.id)
    if status_filter:
        query = query.filter_by(status=status_filter)
    meetings = query.order_by(Meeting.meeting_date.asc(), Meeting.meeting_time.asc()).all()

    total = Meeting.query.filter_by(user_id=current_user.id).count()
    upcoming = Meeting.query.filter_by(user_id=current_user.id, status="Scheduled").count()
    follow_up = Meeting.query.filter_by(user_id=current_user.id, status="Follow-up Needed").count()

    return render_template(
        "dashboard.html",
        meetings=meetings,
        status_filter=status_filter,
        total=total,
        upcoming=upcoming,
        follow_up=follow_up,
    )


@app.route("/meetings/new", methods=["GET", "POST"])
@login_required
def add_meeting():
    if request.method == "POST":
        error = None
        title = request.form.get("title", "").strip()
        partner_branch = request.form.get("partner_branch", "").strip()
        date_str = request.form.get("meeting_date", "")
        time_str = request.form.get("meeting_time", "")

        if not title or not partner_branch or not date_str:
            error = "Title, Partner/Branch, and Date are required."

        meeting_date = None
        meeting_time = None
        if not error:
            try:
                meeting_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                error = "Invalid date format."
        if not error and time_str:
            try:
                meeting_time = datetime.strptime(time_str, "%H:%M").time()
            except ValueError:
                error = "Invalid time format."

        if error:
            flash(error, "error")
            return render_template("meeting_form.html", form_data=request.form, mode="new")

        meeting = Meeting(
            user_id=current_user.id,
            title=title,
            partner_branch=partner_branch,
            meeting_type=request.form.get("meeting_type", "Video Call"),
            meeting_date=meeting_date,
            meeting_time=meeting_time,
            attendees=request.form.get("attendees", ""),
            agenda=request.form.get("agenda", ""),
            discussion_points=request.form.get("discussion_points", ""),
            decisions=request.form.get("decisions", ""),
            action_items=request.form.get("action_items", ""),
            ideas=request.form.get("ideas", ""),
            notes=request.form.get("notes", ""),
            priority=request.form.get("priority", "Medium"),
            status=request.form.get("status", "Scheduled"),
        )
        db.session.add(meeting)
        db.session.commit()
        flash("Meeting saved.", "success")
        return redirect(url_for("dashboard"))

    return render_template("meeting_form.html", form_data={}, mode="new")


@app.route("/meetings/<int:meeting_id>/edit", methods=["GET", "POST"])
@login_required
def edit_meeting(meeting_id):
    meeting = Meeting.query.filter_by(id=meeting_id, user_id=current_user.id).first_or_404()

    if request.method == "POST":
        error = None
        title = request.form.get("title", "").strip()
        partner_branch = request.form.get("partner_branch", "").strip()
        date_str = request.form.get("meeting_date", "")
        time_str = request.form.get("meeting_time", "")

        if not title or not partner_branch or not date_str:
            error = "Title, Partner/Branch, and Date are required."

        meeting_date = None
        meeting_time = None
        if not error:
            try:
                meeting_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                error = "Invalid date format."
        if not error and time_str:
            try:
                meeting_time = datetime.strptime(time_str, "%H:%M").time()
            except ValueError:
                error = "Invalid time format."

        if error:
            flash(error, "error")
            return render_template("meeting_form.html", form_data=request.form, mode="edit", meeting=meeting)

        meeting.title = title
        meeting.partner_branch = partner_branch
        meeting.meeting_type = request.form.get("meeting_type", "Video Call")
        meeting.meeting_date = meeting_date
        meeting.meeting_time = meeting_time
        meeting.attendees = request.form.get("attendees", "")
        meeting.agenda = request.form.get("agenda", "")
        meeting.discussion_points = request.form.get("discussion_points", "")
        meeting.decisions = request.form.get("decisions", "")
        meeting.action_items = request.form.get("action_items", "")
        meeting.ideas = request.form.get("ideas", "")
        meeting.notes = request.form.get("notes", "")
        meeting.priority = request.form.get("priority", "Medium")
        meeting.status = request.form.get("status", "Scheduled")

        db.session.commit()
        flash("Meeting updated.", "success")
        return redirect(url_for("dashboard"))

    form_data = {
        "title": meeting.title,
        "partner_branch": meeting.partner_branch,
        "meeting_type": meeting.meeting_type,
        "meeting_date": meeting.meeting_date.strftime("%Y-%m-%d") if meeting.meeting_date else "",
        "meeting_time": meeting.meeting_time.strftime("%H:%M") if meeting.meeting_time else "",
        "attendees": meeting.attendees,
        "agenda": meeting.agenda,
        "discussion_points": meeting.discussion_points,
        "decisions": meeting.decisions,
        "action_items": meeting.action_items,
        "ideas": meeting.ideas,
        "notes": meeting.notes,
        "priority": meeting.priority,
        "status": meeting.status,
    }
    return render_template("meeting_form.html", form_data=form_data, mode="edit", meeting=meeting)


@app.route("/api/meetings/autosave", methods=["POST"])
@login_required
def autosave_meeting():
    data = request.get_json(silent=True) or {}

    title = (data.get("title") or "").strip()
    partner_branch = (data.get("partner_branch") or "").strip()
    date_str = data.get("meeting_date") or ""

    # Autosave only once the minimum required fields are filled in.
    if not title or not partner_branch or not date_str:
        return jsonify({"saved": False, "reason": "missing_required_fields"})

    try:
        meeting_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"saved": False, "reason": "invalid_date"})

    meeting_time = None
    time_str = data.get("meeting_time") or ""
    if time_str:
        try:
            meeting_time = datetime.strptime(time_str, "%H:%M").time()
        except ValueError:
            meeting_time = None

    meeting_id = data.get("id")
    meeting = None
    if meeting_id:
        meeting = Meeting.query.filter_by(id=meeting_id, user_id=current_user.id).first()

    if meeting is None:
        meeting = Meeting(user_id=current_user.id)
        db.session.add(meeting)

    meeting.title = title
    meeting.partner_branch = partner_branch
    meeting.meeting_type = data.get("meeting_type", "Video Call")
    meeting.meeting_date = meeting_date
    meeting.meeting_time = meeting_time
    meeting.attendees = data.get("attendees", "")
    meeting.agenda = data.get("agenda", "")
    meeting.discussion_points = data.get("discussion_points", "")
    meeting.decisions = data.get("decisions", "")
    meeting.action_items = data.get("action_items", "")
    meeting.ideas = data.get("ideas", "")
    meeting.notes = data.get("notes", "")
    meeting.priority = data.get("priority", "Medium")
    meeting.status = data.get("status", "Scheduled")

    db.session.commit()

    return jsonify({
        "saved": True,
        "id": meeting.id,
        "saved_at": datetime.utcnow().strftime("%H:%M:%S"),
    })

@app.route("/meetings/<int:meeting_id>/delete", methods=["POST"])
@login_required
def delete_meeting(meeting_id):
    meeting = Meeting.query.filter_by(id=meeting_id, user_id=current_user.id).first_or_404()
    db.session.delete(meeting)
    db.session.commit()
    flash("Meeting deleted.", "info")
    return redirect(url_for("dashboard"))


@app.route("/meetings/<int:meeting_id>")
@login_required
def view_meeting(meeting_id):
    meeting = Meeting.query.filter_by(id=meeting_id, user_id=current_user.id).first_or_404()
    return render_template("meeting_detail.html", meeting=meeting)



@app.route("/api/enhance-text", methods=["POST"])
@login_required
def enhance_text():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "No text provided"}), 400

    try:
        genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
        model = genai.GenerativeModel("gemini-3.6-flash")
        prompt = (
            "Fix the grammar and improve the vocabulary of the following meeting-notes "
            "text. Keep the same meaning, structure, and any line breaks. Keep it "
            "professional and concise. Return only the corrected text, nothing else:\n\n"
            + text
        )
        response = model.generate_content(prompt)
        enhanced = (response.text or "").strip()
        return jsonify({"enhanced": enhanced})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=False)
