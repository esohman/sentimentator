#!/usr/bin/env python3
"""Export legacy and EmoMap wheel annotations to one analysis-ready CSV."""

import argparse
import csv
import json

from sentimentator.app import app
from sentimentator.model import db, Annotation, Sentence, User


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', nargs='?', default='emomap_annotations.csv')
    args = parser.parse_args()

    with app.app_context(), open(args.output, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow([
            'annotation_id', 'participant_id', 'username', 'sentence_id', 'text',
            'scheme', 'coarse', 'association_count', 'rt_ms', 'legacy_intensity',
            'wheel_points_json'
        ])
        for row in Annotation.query.order_by(Annotation._aid).all():
            user = db.session.get(User, row._uid)
            sentence = db.session.get(Sentence, row._sid)
            try:
                data = json.loads(row._annotation)
            except Exception:
                data = {'scheme': 'legacy', 'raw': row._annotation}
            points = data.get('wheel_points', [])
            writer.writerow([
                row._aid,
                row._uid,
                user._user if user else '',
                row._sid,
                str(sentence) if sentence else '',
                data.get('scheme', 'legacy'),
                data.get('coarse', ''),
                data.get('association_count', len(points)),
                data.get('rt_ms', ''),
                row._intensity,
                json.dumps(points, ensure_ascii=False),
            ])


if __name__ == '__main__':
    main()
