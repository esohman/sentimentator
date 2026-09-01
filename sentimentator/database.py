# -*- coding: utf-8 -*-
"""Database operations for EmoMap Sentimentator."""

from datetime import datetime, timezone
import json
import secrets

from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from sentimentator.emomap import (
    SCHEME_VERSION,
    WHEEL_VERSION,
    VALID_COARSE,
    build_schedule,
    choose_arm,
    parse_points,
    stable_seed,
)
from sentimentator.meta import Status
from sentimentator.model import (
    Annotation,
    AnnotationPoint,
    ParticipantStudy,
    ParticipantStudyItem,
    Study,
    StudyItem,
    db,
)


def utcnow():
    return datetime.now(timezone.utc)


def init(app):
    db.init_app(app)


def create_schema():
    """Create missing tables. Safe to call repeatedly on a fresh/current schema."""
    db.create_all()


def get_username(_user_id=None):
    return current_user.user


def _study_identity(app_config=None):
    from flask import current_app

    cfg = app_config or current_app.config
    return cfg["EMOMAP_STUDY_KEY"], str(cfg["EMOMAP_STUDY_VERSION"])


def get_active_study():
    study_key, version = _study_identity()
    return Study.query.filter_by(study_key=study_key, version=version, active=True).first()


def _study_config(study):
    try:
        config = json.loads(study.config_json or "{}")
    except json.JSONDecodeError:
        config = {}
    if not isinstance(config, dict):
        config = {}
    return config


def get_or_create_participant_study(user_id):
    """Create a participant record and immutable trial schedule on first use."""
    study = get_active_study()
    if study is None:
        return None

    participant = ParticipantStudy.query.filter_by(user_id=user_id, study_id=study.id).first()
    if participant is not None:
        return participant

    config = _study_config(study)
    seed = stable_seed(study.study_key, study.version, user_id, secrets.token_hex(8))
    arm = choose_arm(config, seed)
    min_lag = int(config.get("min_target_lag", 8))

    items = StudyItem.query.filter_by(study_id=study.id, active=True).all()
    ordered = build_schedule(items, arm=arm, seed=seed, min_target_lag=min_lag)
    if not ordered:
        return None

    participant = ParticipantStudy(
        user_id=user_id,
        study_id=study.id,
        arm=arm,
        schedule_seed=seed,
    )
    db.session.add(participant)
    db.session.flush()

    for trial_number, item in enumerate(ordered, start=1):
        db.session.add(
            ParticipantStudyItem(
                participant_study_id=participant.id,
                item_id=item.id,
                trial_number=trial_number,
            )
        )

    try:
        db.session.commit()
    except IntegrityError:
        # A concurrent first request may have created the schedule first.
        db.session.rollback()
        participant = ParticipantStudy.query.filter_by(
            user_id=user_id, study_id=study.id
        ).first()
    return participant


def get_current_trial(user_id):
    participant = get_or_create_participant_study(user_id)
    if participant is None:
        return None, None

    trial = (
        ParticipantStudyItem.query
        .filter_by(participant_study_id=participant.id, completed_at=None)
        .order_by(ParticipantStudyItem.trial_number)
        .first()
    )
    if trial is None:
        if participant.completed_at is None:
            participant.completed_at = utcnow()
            db.session.commit()
        return participant, None

    if trial.started_at is None:
        trial.started_at = utcnow()
        db.session.commit()
    return participant, trial


def get_progress(user_id):
    study = get_active_study()
    if study is None:
        return {"completed": 0, "total": 0, "percent": 0, "finished": False}

    participant = ParticipantStudy.query.filter_by(user_id=user_id, study_id=study.id).first()
    if participant is None:
        total = StudyItem.query.filter_by(study_id=study.id, active=True).count()
        return {"completed": 0, "total": total, "percent": 0, "finished": False}

    total = ParticipantStudyItem.query.filter_by(participant_study_id=participant.id).count()
    completed = ParticipantStudyItem.query.filter(
        ParticipantStudyItem.participant_study_id == participant.id,
        ParticipantStudyItem.completed_at.isnot(None),
    ).count()
    percent = int(round(100 * completed / total)) if total else 0
    return {
        "completed": completed,
        "total": total,
        "percent": percent,
        "finished": bool(total and completed == total),
        "arm": participant.arm,
    }


def get_score(user_id):
    return get_progress(user_id)["completed"]


def _parse_rt(raw):
    if raw in (None, ""):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def save_annotation(req, user_id):
    """Validate and atomically save one wheel annotation.

    The transaction inserts the Annotation row, inserts all AnnotationPoint rows,
    and marks the scheduled trial complete.  Either all three operations commit
    or none do.  participant_study_item_id and submission_id are independently
    unique, making browser retries/double-clicks idempotent.
    """
    try:
        trial_id = int(req.form.get("trial-id", ""))
    except (TypeError, ValueError):
        return Status.ERR_TRIAL

    submission_id = (req.form.get("submission-id") or "").strip()
    if not submission_id or len(submission_id) > 64:
        return Status.ERR_SUBMISSION

    coarse = req.form.get("sentiment")
    if coarse not in VALID_COARSE:
        return Status.ERR_COARSE

    try:
        points = parse_points(req.form.get("wheel-points", ""))
    except ValueError:
        return Status.ERR_WHEEL

    participant, current_trial = get_current_trial(user_id)
    if participant is None:
        return Status.ERR_STUDY

    trial = db.session.get(ParticipantStudyItem, trial_id)
    if (
        trial is None
        or trial.participant_study_id != participant.id
        or trial.item.study_id != participant.study_id
    ):
        return Status.ERR_TRIAL

    # Already saved: browser retransmission or a double click. Treat as success.
    if trial.completed_at is not None or trial.annotation is not None:
        return Status.OK

    # Prevent a manipulated or stale browser tab from submitting a later trial.
    if current_trial is None or current_trial.id != trial.id:
        return Status.ERR_TRIAL

    annotation = Annotation(
        participant_study_item_id=trial.id,
        item_id=trial.item_id,
        user_id=user_id,
        submission_id=submission_id,
        coarse_label=coarse,
        association_count=len(points),
        response_time_ms=_parse_rt(req.form.get("rt-ms")),
        scheme_version=SCHEME_VERSION,
        wheel_version=WHEEL_VERSION,
    )
    db.session.add(annotation)
    db.session.flush()

    for index, point in enumerate(points, start=1):
        db.session.add(
            AnnotationPoint(
                annotation_id=annotation.id,
                point_order=index,
                x_norm=point["x_norm"],
                y_norm=point["y_norm"],
                canonical_x=point["canonical_x"],
                canonical_y=point["canonical_y"],
                dx=point["dx"],
                dy=point["dy"],
                radius=point["radius"],
                angle_deg=point["angle_deg"],
            )
        )

    trial.completed_at = utcnow()

    try:
        db.session.flush()
        remaining = ParticipantStudyItem.query.filter(
            ParticipantStudyItem.participant_study_id == participant.id,
            ParticipantStudyItem.completed_at.is_(None),
        ).count()
        if remaining == 0:
            participant.completed_at = utcnow()
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing_trial = Annotation.query.filter_by(
            participant_study_item_id=trial_id
        ).first()
        if existing_trial is not None and existing_trial.user_id == user_id:
            return Status.OK
        existing_submission = Annotation.query.filter_by(
            submission_id=submission_id
        ).first()
        if (
            existing_submission is not None
            and existing_submission.user_id == user_id
            and existing_submission.participant_study_item_id == trial_id
        ):
            return Status.OK
        return Status.ERR_DUPLICATE

    return Status.OK


def admin_progress_rows():
    """Return instructor-facing completion rows for the configured study."""
    study = get_active_study()
    if study is None:
        return []

    rows = []
    for participant in ParticipantStudy.query.filter_by(study_id=study.id).all():
        total = ParticipantStudyItem.query.filter_by(
            participant_study_id=participant.id
        ).count()
        completed = ParticipantStudyItem.query.filter(
            ParticipantStudyItem.participant_study_id == participant.id,
            ParticipantStudyItem.completed_at.isnot(None),
        ).count()
        rows.append(
            {
                "participant_id": participant.user_id,
                "username": participant.user._user,
                "arm": participant.arm,
                "completed": completed,
                "total": total,
                "finished": completed == total and total > 0,
                "started_at": participant.started_at,
                "completed_at": participant.completed_at,
            }
        )
    return sorted(rows, key=lambda row: row["username"].lower())
