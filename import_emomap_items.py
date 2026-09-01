#!/usr/bin/env python3
"""Import EmoMap word/context items from CSV into the existing Sentence table.

CSV columns: language,target,context
The first occurrence of target in context is wrapped internally as [[target]].
For isolated words, context may equal target.
"""

import argparse
import csv

from sentimentator.app import app
from sentimentator.model import db, Language, Sentence


def marked_text(target, context):
    if '[[' in context and ']]' in context:
        return context
    idx = context.lower().find(target.lower())
    if idx < 0:
        raise ValueError(f'Target {target!r} not found in context {context!r}')
    return context[:idx] + '[[' + context[idx:idx+len(target)] + ']]' + context[idx+len(target):]


def language_id(code):
    lang = Language.query.filter_by(_language=code).first()
    if lang is None:
        lang = Language(language=code)
        db.session.add(lang)
        db.session.flush()
    return lang._lid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('csv_file')
    args = parser.parse_args()

    added = 0
    with app.app_context(), open(args.csv_file, newline='', encoding='utf-8-sig') as f:
        db.create_all()
        for row in csv.DictReader(f):
            code = row.get('language', 'en').strip() or 'en'
            target = row['target'].strip()
            context = row['context'].strip()
            text = marked_text(target, context)
            lid = language_id(code)
            if Sentence.query.filter_by(_lid=lid, _sentence=text).first() is None:
                db.session.add(Sentence(text, lid, None, None))
                added += 1
        db.session.commit()
    print(f'Imported {added} new items.')


if __name__ == '__main__':
    main()
