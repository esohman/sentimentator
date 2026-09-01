# -*- coding: utf-8 -*-

import json
import math

from flask_login import current_user
from sqlalchemy import func

from sentimentator.meta import Status
from sentimentator.model import (
    db,
    Language,
    Sentence,
    Annotation,
    TestSentence,
    UserSeenSentence,
)


VALID_FINE_SENTIMENTS = ['ant', 'joy', 'sur', 'ang', 'fea', 'dis', 'tru', 'sad']
VALID_COARSE = {'pos', 'neg', 'neither', 'both'}
SCHEME = 'emomap-wheel-v2'

# Geometry of Emily Öhman's supplied 960 x 720 inverted Plutchik image.
# Raw normalized x/y coordinates are also stored, so this calibration can be
# revised later without recollecting annotations.
WHEEL_WIDTH = 960.0
WHEEL_HEIGHT = 720.0
WHEEL_CENTER_X = 480.0
WHEEL_CENTER_Y = 368.0
WHEEL_MAX_RADIUS = 320.0
MAX_WHEEL_POINTS = 8


def init(app):
    """Initiate data model. Database creation remains in the import scripts."""
    db.init_app(app)


def get_username(user_id):
    return current_user.user


def get_score(user_id):
    return Annotation.query.filter_by(_uid=user_id).count()


def count(user_id, likeness):
    q = Annotation.query.filter_by(_uid=user_id).filter(
        Annotation._annotation.like(likeness)
    )
    return q.count()


def get_seen_sentence(user_id):
    return {
        s._tsid for s in UserSeenSentence.query.filter_by(_uid=user_id).all()
    }


def reset_user_sentences(user_id):
    Annotation.query.filter_by(_uid=user_id).delete()
    db.session.commit()


def reset_user_test_sentences(user_id):
    UserSeenSentence.query.filter_by(_uid=user_id).delete()
    Annotation.query.filter_by(_uid=user_id).delete()
    db.session.commit()


def get_random_sentence(lang, user_id=None):
    """Fetch a random sentence, excluding items already annotated by this user."""
    language = Language.query.filter_by(_language=lang).first()
    if language is None:
        return None

    query = Sentence.query.filter_by(_lid=language._lid)
    if user_id is not None:
        seen = db.session.query(Annotation._sid).filter(Annotation._uid == user_id)
        query = query.filter(~Sentence._sid.in_(seen))
    return query.order_by(func.random()).first()


def get_test_sentence(lang, user_id, seen_tsids):
    """Fetch an unseen test sentence and mark it as seen."""
    language = Language.query.filter_by(_language=lang).first()
    if language is None:
        return None

    sentence = (
        TestSentence.query.filter_by(_lid=language._lid)
        .filter(~TestSentence._tsid.in_(seen_tsids))
        .first()
    )
    if sentence:
        db.session.add(UserSeenSentence(_uid=user_id, _tsid=sentence._tsid))
        db.session.commit()
    return sentence


def _geometry(x_norm, y_norm):
    px = x_norm * WHEEL_WIDTH
    py = y_norm * WHEEL_HEIGHT
    dx = px - WHEEL_CENTER_X
    dy = WHEEL_CENTER_Y - py  # positive y points upward
    radius_px = math.hypot(dx, dy)
    radius = radius_px / WHEEL_MAX_RADIUS
    angle = (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0
    return {
        'x': round(x_norm, 6),
        'y': round(y_norm, 6),
        'px': round(px, 2),
        'py': round(py, 2),
        'dx': round(dx, 2),
        'dy': round(dy, 2),
        'radius': round(radius, 6),
        'angle_deg': round(angle, 3),
    }


def _parse_points(raw):
    try:
        points = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None

    if not isinstance(points, list) or not (1 <= len(points) <= MAX_WHEEL_POINTS):
        return None

    clean = []
    for point in points:
        try:
            x = float(point['x'])
            y = float(point['y'])
        except (KeyError, TypeError, ValueError):
            return None
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            return None
        clean.append(_geometry(x, y))
    return clean


def save_annotation(req, user_id, test=False):
    """Validate and save an EmoMap wheel annotation.

    The existing Annotation schema is retained. The complete multi-point wheel
    annotation is JSON-encoded in ``annotation``; the first point's radial
    distance is mirrored in the legacy ``intensity`` column.
    """
    try:
        sentence_id = int(req.form.get('sentence-id', ''))
    except (TypeError, ValueError):
        return Status.ERR_SENTENCE

    item_model = TestSentence if test else Sentence
    sentence = db.session.get(item_model, sentence_id)
    if sentence is None:
        return Status.ERR_SENTENCE

    # Normal annotation items should never be saved twice accidentally. Test
    # items retain the existing UserSeenSentence mechanism because test IDs can
    # overlap with ordinary Sentence IDs in the legacy schema.
    if not test:
        existing = Annotation.query.filter_by(_uid=user_id, _sid=sentence_id).first()
        if existing is not None:
            return Status.OK

    coarse = req.form.get('sentiment')
    if coarse not in VALID_COARSE:
        return Status.ERR_COARSE

    points = _parse_points(req.form.get('wheel-points', ''))
    if points is None:
        return Status.ERR_WHEEL

    try:
        rt_ms = int(req.form.get('rt-ms', ''))
        if rt_ms < 0:
            rt_ms = None
    except (TypeError, ValueError):
        rt_ms = None

    annotation = {
        'scheme': SCHEME,
        'coarse': coarse,
        'wheel_points': points,
        'association_count': len(points),
        'rt_ms': rt_ms,
        'item_type': 'test_sentence' if test else 'sentence',
    }

    intensity = points[0]['radius']
    row = Annotation(
        user_id=user_id,
        sentence_id=sentence_id,
        annotation=json.dumps(annotation, ensure_ascii=False),
        intensity=intensity,
    )
    db.session.add(row)
    db.session.commit()
    return Status.OK
