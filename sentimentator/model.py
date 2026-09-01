# -*- coding: utf-8 -*-
"""Database models for the EmoMap version of Sentimentator.

The legacy Sentence/TestSentence schema is deliberately not used by the EmoMap
annotation workflow.  A study item is an experimental stimulus; a participant
receives a persistent trial schedule; and each submitted annotation owns one or
more geometric wheel points.
"""

from datetime import datetime, timezone
import sqlite3

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, UniqueConstraint, event
from sqlalchemy.engine import Engine
from werkzeug.security import check_password_hash, generate_password_hash


def utcnow():
    return datetime.now(timezone.utc)


db = SQLAlchemy()


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, _connection_record):
    """Use SQLite settings appropriate for a small concurrent web study.

    WAL permits readers while a write transaction is active.  busy_timeout
    makes short write-contention events wait instead of immediately failing.
    Foreign keys are disabled by default in SQLite and must be enabled for each
    connection.
    """
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=10000")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


class User(db.Model, UserMixin):
    __tablename__ = "user"

    _uid = db.Column("id", db.Integer, primary_key=True)
    _user = db.Column("user", db.String(80), unique=True, nullable=False, index=True)
    _pass = db.Column("pass", db.String, nullable=False)

    participant_studies = db.relationship(
        "ParticipantStudy", back_populates="user", cascade="all, delete-orphan"
    )

    def __init__(self, username):
        self._user = username

    @property
    def user(self):
        return self._user

    @user.setter
    def user(self, username):
        self._user = username

    def get_id(self):
        return str(self._uid)

    def set_password(self, password):
        self._pass = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self._pass, password)


class Study(db.Model):
    __tablename__ = "study"
    __table_args__ = (
        UniqueConstraint("study_key", "version", name="uq_study_key_version"),
    )

    id = db.Column(db.Integer, primary_key=True)
    study_key = db.Column(db.String(80), nullable=False, index=True)
    version = db.Column(db.String(32), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    config_json = db.Column(db.Text, nullable=False, default="{}")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    items = db.relationship(
        "StudyItem", back_populates="study", cascade="all, delete-orphan"
    )
    participants = db.relationship(
        "ParticipantStudy", back_populates="study", cascade="all, delete-orphan"
    )


class StudyItem(db.Model):
    __tablename__ = "study_item"
    __table_args__ = (
        UniqueConstraint("study_id", "item_key", name="uq_study_item_key"),
        CheckConstraint(
            "condition IN ('isolated','context','control','repeat')",
            name="ck_study_item_condition",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    study_id = db.Column(
        db.Integer, db.ForeignKey("study.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_key = db.Column(db.String(160), nullable=False)
    language = db.Column(db.String(16), nullable=False, default="en", index=True)
    target = db.Column(db.String(200), nullable=False)
    text = db.Column(db.Text, nullable=False)
    condition = db.Column(db.String(32), nullable=False)
    sense = db.Column(db.String(200))
    source = db.Column(db.String(200))
    target_group = db.Column(db.String(200), nullable=False, index=True)
    base_item_key = db.Column(db.String(160))
    # Optional arm name.  If a participant is assigned this arm, this context
    # is moved before the isolated item for its target group.
    prime_arm = db.Column(db.String(80), index=True)
    metadata_json = db.Column(db.Text, nullable=False, default="{}")
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    study = db.relationship("Study", back_populates="items")
    scheduled_trials = db.relationship("ParticipantStudyItem", back_populates="item")
    annotations = db.relationship("Annotation", back_populates="item")

    def __str__(self):
        return self.text


class ParticipantStudy(db.Model):
    __tablename__ = "participant_study"
    __table_args__ = (
        UniqueConstraint("user_id", "study_id", name="uq_participant_study"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    study_id = db.Column(
        db.Integer, db.ForeignKey("study.id", ondelete="CASCADE"), nullable=False, index=True
    )
    arm = db.Column(db.String(80), nullable=False, default="main")
    schedule_seed = db.Column(db.Integer, nullable=False)
    started_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    completed_at = db.Column(db.DateTime(timezone=True))

    user = db.relationship("User", back_populates="participant_studies")
    study = db.relationship("Study", back_populates="participants")
    trials = db.relationship(
        "ParticipantStudyItem",
        back_populates="participant_study",
        cascade="all, delete-orphan",
        order_by="ParticipantStudyItem.trial_number",
    )


class ParticipantStudyItem(db.Model):
    __tablename__ = "participant_study_item"
    __table_args__ = (
        UniqueConstraint("participant_study_id", "item_id", name="uq_participant_item"),
        UniqueConstraint("participant_study_id", "trial_number", name="uq_participant_trial"),
        CheckConstraint("trial_number >= 1", name="ck_trial_number_positive"),
    )

    id = db.Column(db.Integer, primary_key=True)
    participant_study_id = db.Column(
        db.Integer,
        db.ForeignKey("participant_study.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id = db.Column(
        db.Integer, db.ForeignKey("study_item.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trial_number = db.Column(db.Integer, nullable=False)
    started_at = db.Column(db.DateTime(timezone=True))
    completed_at = db.Column(db.DateTime(timezone=True))

    participant_study = db.relationship("ParticipantStudy", back_populates="trials")
    item = db.relationship("StudyItem", back_populates="scheduled_trials")
    annotation = db.relationship(
        "Annotation", back_populates="trial", uselist=False, cascade="all, delete-orphan"
    )


class Annotation(db.Model):
    __tablename__ = "annotation"
    __table_args__ = (
        UniqueConstraint("participant_study_item_id", name="uq_annotation_trial"),
        UniqueConstraint("submission_id", name="uq_annotation_submission"),
        CheckConstraint(
            "coarse_label IN ('pos','neg','neither','both')",
            name="ck_annotation_coarse",
        ),
        CheckConstraint(
            "association_count BETWEEN 1 AND 8", name="ck_annotation_point_count"
        ),
        CheckConstraint(
            "response_time_ms IS NULL OR response_time_ms >= 0",
            name="ck_annotation_rt",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    participant_study_item_id = db.Column(
        db.Integer,
        db.ForeignKey("participant_study_item.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id = db.Column(
        db.Integer, db.ForeignKey("study_item.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    submission_id = db.Column(db.String(64), nullable=False)
    coarse_label = db.Column(db.String(16), nullable=False)
    association_count = db.Column(db.Integer, nullable=False)
    response_time_ms = db.Column(db.Integer)
    scheme_version = db.Column(db.String(80), nullable=False)
    wheel_version = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    trial = db.relationship("ParticipantStudyItem", back_populates="annotation")
    item = db.relationship("StudyItem", back_populates="annotations")
    user = db.relationship("User")
    points = db.relationship(
        "AnnotationPoint",
        back_populates="annotation",
        cascade="all, delete-orphan",
        order_by="AnnotationPoint.point_order",
    )


class AnnotationPoint(db.Model):
    __tablename__ = "annotation_point"
    __table_args__ = (
        UniqueConstraint("annotation_id", "point_order", name="uq_annotation_point_order"),
        CheckConstraint("point_order BETWEEN 1 AND 8", name="ck_point_order"),
        CheckConstraint("x_norm BETWEEN 0.0 AND 1.0", name="ck_point_x_norm"),
        CheckConstraint("y_norm BETWEEN 0.0 AND 1.0", name="ck_point_y_norm"),
    )

    id = db.Column(db.Integer, primary_key=True)
    annotation_id = db.Column(
        db.Integer, db.ForeignKey("annotation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    point_order = db.Column(db.Integer, nullable=False)

    # Raw measurement.  These two values are the authoritative wheel click.
    x_norm = db.Column(db.Float, nullable=False)
    y_norm = db.Column(db.Float, nullable=False)

    # Derived geometry for convenient analysis.  It can always be recomputed
    # from x_norm/y_norm + wheel_version.
    canonical_x = db.Column(db.Float, nullable=False)
    canonical_y = db.Column(db.Float, nullable=False)
    dx = db.Column(db.Float, nullable=False)
    dy = db.Column(db.Float, nullable=False)
    radius = db.Column(db.Float, nullable=False)
    angle_deg = db.Column(db.Float, nullable=False)

    annotation = db.relationship("Annotation", back_populates="points")
