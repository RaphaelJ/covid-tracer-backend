#!/bin/#!/usr/bin/env python3

import os, datetime

from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy

import wtforms

DAILY_KEY_SIZE = 256 / 8 # Bytes.

INCUBATION_PERIOD = 5
SYMPTOMS_TO_VIRUS_NEGATIVE = 11

app = Flask(__name__)
app.config.from_object(os.environ['APP_SETTINGS'])

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

import models

@app.route('/cases.json')
def cases():
    """Returns the actives SARS-CoV-2 cases as a JSON document."""

    return {
        'cases': [
            {
                'key': key.key,
                'date': key.date.isoformat(),
                'type': 'positive' if key.is_tested else 'symptomatic',
            }
            for key in models.DailyKey.query.all()
        ]
    }

class DailyKeyForm(wtforms.Form):
    date = wtforms.DateField('Daily key date', [wtforms.validators.InputRequired()])
    value = wtforms.StringField('Daily key value (hexadecimal string)', [
        wtforms.validators.InputRequired(),
        wtforms.validators.Length(min=DAILY_KEY_SIZE * 2, max=DAILY_KEY_SIZE * 2)
    ])

class NotifyForm(wtforms.Form):
    is_tested = wtforms.BooleanField('Is tested against COVID-19', default=False)
    comment = wtforms.StringField('Comment', [wtforms.validators.Length(max=1000)])

    keys = wtforms.FieldList(wtforms.FormField(DailyKeyForm))

    def validate_keys(form, field):
        if not field.data:
            return

        expected_keys_count = INCUBATION_PERIOD + SYMPTOMS_TO_VIRUS_NEGATIVE

        key_values = set(key['value'] for key in field.data)

        # All keys should be unique, and should match the expected count
        if len(key_values) != expected_keys_count:
            raise wtforms.ValidationError(
                'Should contain {} daily keys.'.format(expected_keys_count)
            )

        key_dates = sorted(key['date'] for key in field.data)

        # There should not be any missing date
        prev_date = None
        for date in key_dates:
            if prev_date is not None and date != prev_date + datetime.timedelta(days=1):
                raise wtforms.ValidationError('Key dates should not contain gaps.')

            prev_date = date

        if key_dates[0] > datetime.datetime.utcnow().date():
            raise wtforms.ValidationError('Key dates can not all be in the future.')

@app.route('/notify', methods=['POST'])
def notify():
    """
    Notifies a new positive or symptomatic case of COVID-19 and returns a `201 Created` response.

    Returns a `403 Forbidden` response when trying to notify an already reported case.

    Returns a `429 Too many requests` response when getting more than 5 requests per 5 minutes from
    the same remote host.
    """

    form = NotifyForm(request.form)

    if form.validate():
        # Does not allow to override an already reported case.
        already_exists = models.DailyKey.query                                          \
            .filter(models.DailyKey.key.in_(key['value'] for key in form.keys.data))    \
            .count()

        if already_exists > 0:
            return 'Forbidden', 403

        # Does not allow more than 5 requests per IP per hour.
        #
        # We allow a reasonable amount of devices from the same address to notify cases in a short
        # period of time as multiple cases can legitimately originate from the same household or
        # organisation.

        if not request.headers.getlist("X-Forwarded-For"):
            remote_addr = request.remote_addr
        else:
            remote_addr = request.headers.getlist("X-Forwarded-For")[0]

        user_agent = request.headers.get('User-Agent')

        one_hour_ago = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
        prev_reporting_count = models.Request.query                         \
            .filter_by(remote_addr=remote_addr)                             \
            .filter(models.Request.created_at >= one_hour_ago)              \
            .count()

        if prev_reporting_count >= 5:
            return 'Too many requests', 429

        # --

        for key in form.keys.data:
            db_key = models.DailyKey(
                key=key['value'],
                date=key['date'],
                is_tested=form.is_tested.data,
            )
            models.db.session.add(db_key)

        req = models.Request(
            remote_addr=remote_addr,
            user_agent=user_agent,
            comment=form.comment.data,
        )
        models.db.session.add(req)

        models.db.session.commit()

        return 'Created', 201
    else:
        return 'Bad request', 400

if __name__ == '__main__':
    models.db.create_all(app=app)

    app.run()
