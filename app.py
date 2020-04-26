#!/bin/#!/usr/bin/env python3

# Copyright 2020 Raphael Javaux
#
# This file is part of CovidTracer.
#
# CovidTracer is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# CovidTracer is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with CovidTracer. If not, see<https://www.gnu.org/licenses/>.

import os, datetime

from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy

import wtforms

DAILY_KEY_SIZE = 256 / 8 # Bytes.

INCUBATION_PERIOD = 5
SYMPTOMS_TO_VIRUS_NEGATIVE = 11

INFECTION_PERIOD = INCUBATION_PERIOD + SYMPTOMS_TO_VIRUS_NEGATIVE

app = Flask(__name__)
app.config.from_object(os.environ['APP_SETTINGS'])

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

import models

@app.route('/cases.json')
def cases():
    """Returns the actives SARS-CoV-2 cases as a JSON document."""

    now = datetime.datetime.utcnow()
    today = now.date()

    # Does not return keys that are older than a typical infection period.
    min_date = today - datetime.timedelta(days=INFECTION_PERIOD)

    # Only return keys from the past days to avoid impersonation
    max_date = today

    # Releases new keys only twice a day to avoid keys being grouped by the submitting user.
    if now.time().hour >= 12:
        min_creation_at = datetime.datetime.combine(today, datetime.time(hour=12))
    else:
        min_creation_at = datetime.datetime.combine(today, datetime.time(hour=0))

    keys = models.DailyKey.query                                                \
        .filter(models.DailyKey.date > min_date)                                \
        .filter(models.DailyKey.date < max_date)                                \
        .filter(models.DailyKey.created_at <= min_creation_at)                  \
        .order_by(models.DailyKey.key)                                          \
        .all()

    return {
        'cases': [
            {
                'key': key.key,
                'date': key.date.isoformat(),
                'type': 'positive' if key.is_tested else 'symptomatic',
            }
            for key in keys
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
