# -*- coding: utf-8 -*-

import logging
import os
from datetime import datetime
from functools import wraps, update_wrapper

from dotenv import load_dotenv
from flask import Flask, render_template, request, flash, redirect, url_for, make_response
from flask_login import LoginManager, current_user, logout_user, login_required, login_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Length, EqualTo
from werkzeug.http import http_date

from sentimentator.meta import Message, Status
from sentimentator.database import (
    init,
    get_random_sentence,
    get_test_sentence,
    save_annotation,
    get_score,
    get_username,
    count,
    get_seen_sentence,
    reset_user_sentences,
    reset_user_test_sentences,
)
from sentimentator.model import db


load_dotenv()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///db.sqlite')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'change-me-before-production')

login = LoginManager()
login.init_app(app)
login.login_view = 'login'
logging.basicConfig(level=logging.DEBUG)


from sentimentator.model import User


@login.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


init(app)


def disable_cache(view):
    @wraps(view)
    def disable_cache_inner(*args, **kwargs):
        resp = make_response(view(*args, **kwargs))
        resp.headers['Last-Modified'] = http_date(datetime.now())
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '-1'
        return resp
    return update_wrapper(disable_cache_inner, view)


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('SIGN IN')


class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=4, max=80)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register')


def split_target(text):
    """Parse one [[target]] marker without emitting unsafe HTML.

    Existing Sentimentator sentences without a marker still work: the entire
    sentence is displayed as the target. New EmoMap study items should use
    ``[[target]]`` in the imported text.
    """
    start = text.find('[[')
    end = text.find(']]', start + 2) if start >= 0 else -1
    if start >= 0 and end > start:
        return text[:start], text[start + 2:end], text[end + 2:]
    return '', text, ''


def _render_annotation(template, lang, sentence, sentence_id, score, username, form_action):
    prefix, target, suffix = split_target(str(sentence))
    return render_template(
        template,
        lang=lang,
        sentence=sentence,
        sentence_id=sentence_id,
        prefix=prefix,
        target=target,
        suffix=suffix,
        score=score,
        username=username,
        form_action=form_action,
    )


@app.route('/')
def index():
    if current_user.is_authenticated:
        user_id = current_user._uid
        return render_template('index.html', score=get_score(user_id), username=get_username(user_id))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(_user=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('Invalid username or password...')
            return redirect(url_for('login'))
        login_user(user)
        return redirect(url_for('index'))
    return render_template('login.html', title='SIGN IN', form=form)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = RegistrationForm()
    if form.validate_on_submit():
        existing_user = User.query.filter_by(_user=form.username.data).first()
        if existing_user:
            flash('Username already taken. Please choose a different one.', 'error')
            return render_template('register.html', form=form)

        user = User(form.username.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html', title='REGISTER', form=form)


@app.route('/language')
@login_required
def language():
    user_id = current_user._uid
    return render_template('language.html', score=get_score(user_id), username=get_username(user_id))


@app.route('/annotate/<lang>', methods=['GET', 'POST'])
@disable_cache
@login_required
def annotate(lang):
    user_id = current_user._uid
    username = get_username(user_id)

    if request.method == 'POST':
        status = save_annotation(request, user_id, test=False)
        if status == Status.ERR_COARSE:
            app.logger.error(Message.INPUT_COARSE)
            flash('Please choose Positive, Negative, Neither, or Both.')
        elif status == Status.ERR_WHEEL:
            app.logger.error(Message.INPUT_WHEEL)
            flash('Please select at least one association on the wheel.')
        elif status == Status.ERR_SENTENCE:
            app.logger.error(Message.INPUT_SENTENCE)
            flash('The annotation item could not be found.')

    score = get_score(user_id)
    sen = get_random_sentence(lang, user_id)
    if sen is None:
        flash('There are no unseen sentences for the selected language!')
        return redirect(url_for('language'))

    return _render_annotation(
        'annotate.html', lang, sen, sen.sid, score, username,
        url_for('annotate', lang=lang)
    )


@app.route('/test-annotate/<lang>', methods=['GET', 'POST'])
@disable_cache
@login_required
def test_annotate(lang):
    user_id = current_user._uid
    username = get_username(user_id)

    if request.method == 'POST':
        status = save_annotation(request, user_id, test=True)
        if status == Status.ERR_COARSE:
            app.logger.error(Message.INPUT_COARSE)
            flash('Please choose Positive, Negative, Neither, or Both.')
        elif status == Status.ERR_WHEEL:
            app.logger.error(Message.INPUT_WHEEL)
            flash('Please select at least one association on the wheel.')
        elif status == Status.ERR_SENTENCE:
            app.logger.error(Message.INPUT_SENTENCE)
            flash('The annotation item could not be found.')

    seen_tsids = get_seen_sentence(user_id)
    sen = get_test_sentence(lang, user_id, seen_tsids)
    score = get_score(user_id)
    if sen is None:
        flash('There are no unseen test sentences for the selected language!')
        return redirect(url_for('language'))

    return _render_annotation(
        'test_annotate.html', lang, sen, sen.tsid, score, username,
        url_for('test_annotate', lang=lang)
    )


@app.route('/stats')
@login_required
def stats():
    user_id = current_user._uid
    return render_template(
        'stats.html',
        score=get_score(user_id),
        username=get_username(user_id),
        positive=count(user_id, '%pos%'),
        negative=count(user_id, '%neg%'),
        neither=count(user_id, '%neither%'),
        both=count(user_id, '%both%'),
        legacy_neutral=count(user_id, '%neu%'),
    )


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/reset_sentences', methods=['GET'])
@login_required
def reset_sentences():
    user_id = current_user._uid
    reset_user_sentences(user_id)
    return render_template('index.html', score=get_score(user_id), username=get_username(user_id))


@app.route('/reset_test_sentences', methods=['GET'])
@login_required
def reset_test_sentences():
    user_id = current_user._uid
    reset_user_test_sentences(user_id)
    return render_template('index.html', score=get_score(user_id), username=get_username(user_id))
