# -*- coding: utf-8 -*-
"""Flask application for the EmoMap annotation study."""

from datetime import datetime
from functools import wraps, update_wrapper
import logging
import os

from dotenv import load_dotenv
from flask import Flask, abort, flash, make_response, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from werkzeug.http import http_date
from sqlalchemy import text
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, EqualTo, Length

from sentimentator.database import (
    admin_progress_rows,
    get_active_study,
    get_current_trial,
    get_progress,
    get_score,
    get_username,
    init,
    save_annotation,
)
from sentimentator.meta import Message, Status
from sentimentator.model import User, db


load_dotenv()


def required_env(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"{name} is required. Copy .env.example to .env for local use, "
            "or pass it explicitly to the Docker container."
        )
    return value


app = Flask(__name__)
app.config.update(
    SQLALCHEMY_DATABASE_URI=required_env("DATABASE_URL"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SQLALCHEMY_ENGINE_OPTIONS={
        "pool_pre_ping": True,
        "connect_args": {"timeout": 10},
    },
    SECRET_KEY=required_env("SECRET_KEY"),
    EMOMAP_STUDY_KEY=os.getenv("EMOMAP_STUDY_KEY", "emomap-pilot"),
    EMOMAP_STUDY_VERSION=os.getenv("EMOMAP_STUDY_VERSION", "1"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "0") == "1",
    MAX_CONTENT_LENGTH=64 * 1024,
)

init(app)
csrf = CSRFProtect(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
logging.basicConfig(level=logging.INFO)


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


def disable_cache(view):
    @wraps(view)
    def inner(*args, **kwargs):
        response = make_response(view(*args, **kwargs))
        response.headers["Last-Modified"] = http_date(datetime.now())
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "-1"
        return response

    return update_wrapper(inner, view)


class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("SIGN IN")


class RegistrationForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(min=4, max=80)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField(
        "Confirm Password", validators=[DataRequired(), EqualTo("password")]
    )
    submit = SubmitField("Register")


def split_target(text):
    """Parse exactly one [[target]] marker without rendering unsafe HTML."""
    start = text.find("[[")
    end = text.find("]]", start + 2) if start >= 0 else -1
    if start >= 0 and end > start:
        return text[:start], text[start + 2 : end], text[end + 2 :]
    return "", text, ""


def is_admin_user():
    allowed = {
        name.strip().lower()
        for name in os.getenv("ADMIN_USERNAMES", "").split(",")
        if name.strip()
    }
    return bool(current_user.is_authenticated and current_user.user.lower() in allowed)


def flash_save_error(status):
    messages = {
        Status.ERR_COARSE: "Please choose Positive, Negative, Neither, or Both.",
        Status.ERR_WHEEL: "Please select between one and eight associations on the wheel.",
        Status.ERR_TRIAL: "This annotation page is stale. It has been reloaded safely.",
        Status.ERR_STUDY: "The study is not currently available.",
        Status.ERR_SUBMISSION: "The submission identifier was invalid. Please reload the page.",
        Status.ERR_DUPLICATE: "A conflicting duplicate submission was blocked.",
    }
    log_messages = {
        Status.ERR_COARSE: Message.INPUT_COARSE,
        Status.ERR_WHEEL: Message.INPUT_WHEEL,
        Status.ERR_TRIAL: Message.INPUT_TRIAL,
        Status.ERR_STUDY: Message.INPUT_STUDY,
        Status.ERR_SUBMISSION: Message.INPUT_SUBMISSION,
        Status.ERR_DUPLICATE: Message.INPUT_DUPLICATE,
    }
    app.logger.warning(log_messages.get(status, "Annotation save failed"))
    flash(messages.get(status, "The annotation could not be saved. Please try again."), "error")


@app.route("/")
def index():
    if not current_user.is_authenticated:
        return redirect(url_for("login"))
    study = get_active_study()
    progress = get_progress(current_user._uid)
    return render_template(
        "index.html",
        username=get_username(current_user._uid),
        score=get_score(current_user._uid),
        progress=progress,
        study=study,
        is_admin=is_admin_user(),
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(_user=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash("Invalid username or password.", "error")
            return redirect(url_for("login"))
        login_user(user)
        return redirect(url_for("index"))
    return render_template("login.html", title="SIGN IN", form=form)


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    form = RegistrationForm()
    if form.validate_on_submit():
        existing = User.query.filter_by(_user=form.username.data).first()
        if existing is not None:
            flash("Username already taken. Please choose a different one.", "error")
            return render_template("register.html", title="REGISTER", form=form)

        user = User(form.username.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html", title="REGISTER", form=form)


@app.route("/language")
@login_required
def language():
    # Kept as a compatibility endpoint for old bookmarks.  EmoMap's active
    # study controls the available items/language rather than the old OPUS menu.
    return redirect(url_for("annotate"))


@app.route("/annotate", methods=["GET", "POST"])
@disable_cache
@login_required
def annotate():
    user_id = current_user._uid

    if request.method == "POST":
        status = save_annotation(request, user_id)
        if status == Status.OK:
            # POST/Redirect/GET prevents browser refresh from resubmitting data.
            return redirect(url_for("annotate"), code=303)
        flash_save_error(status)
        return redirect(url_for("annotate"), code=303)

    participant, trial = get_current_trial(user_id)
    study = get_active_study()
    if study is None or participant is None:
        flash("No active EmoMap study has been loaded yet.", "error")
        return redirect(url_for("index"))

    progress = get_progress(user_id)
    if trial is None:
        return render_template(
            "complete.html",
            username=get_username(user_id),
            progress=progress,
            study=study,
        )

    item = trial.item
    prefix, target, suffix = split_target(item.text)
    return render_template(
        "annotate.html",
        username=get_username(user_id),
        study=study,
        participant=participant,
        trial=trial,
        item=item,
        prefix=prefix,
        target=target,
        suffix=suffix,
        progress=progress,
        form_action=url_for("annotate"),
    )


@app.route("/annotate/<lang>")
@login_required
def annotate_legacy_language(lang):
    # Compatibility with old /annotate/en links. Language now comes from each
    # StudyItem and cannot be changed by a URL parameter.
    return redirect(url_for("annotate"), code=302)


@app.route("/test-annotate/<lang>")
@login_required
def test_annotate_legacy(lang):
    return redirect(url_for("annotate"), code=302)


@app.route("/stats")
@login_required
def stats():
    return render_template(
        "stats.html",
        username=get_username(current_user._uid),
        progress=get_progress(current_user._uid),
        study=get_active_study(),
    )


@app.route("/admin/progress")
@login_required
def admin_progress():
    if not is_admin_user():
        abort(403)
    return render_template(
        "admin_progress.html",
        rows=admin_progress_rows(),
        study=get_active_study(),
        username=get_username(current_user._uid),
    )


@app.route("/healthz")
def healthz():
    try:
        db.session.execute(text("SELECT 1"))
    except Exception:
        app.logger.exception("Database health check failed")
        return {"status": "error"}, 503
    return {"status": "ok"}, 200


@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("login"))
