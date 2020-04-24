#!/bin/#!/usr/bin/env python3

import os, datetime

from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy

import wtforms

app = Flask(__name__)
app.config.from_object(os.environ['APP_SETTINGS'])

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

import models

@app.route('/cases')
def cases():
    """Returns the actives COVID-19 cases as a JSON document."""

    BEGINS_BEFORE_SYMPTOMS = datetime.timedelta(days=5)
    ENDS_AFTER_SYMPTOMS = datetime.timedelta(days=14)

    return {
        'cases': [
            {
                'covid_tracer_id': case.covid_tracer_id,
                'begins_on': (case.symptoms_onset - BEGINS_BEFORE_SYMPTOMS).isoformat(),
                'ends_on': (case.symptoms_onset + ENDS_AFTER_SYMPTOMS).isoformat(),
            }
            for case in models.Case.query.all()
        ]
    }

class NotifyForm(wtforms.Form):
    symptoms_onset = wtforms.DateField('Symptoms onset date', [wtforms.validators.InputRequired()])
    is_tested = wtforms.BooleanField('Is tested against COVID-19', default=False)
    comment = wtforms.StringField('Comment', [wtforms.validators.Length(max=1000)])

@app.route('/notify/<string:covid_tracer_id>', methods=['POST'])
def notify(covid_tracer_id):
    """
    Notifies a new positive or symptomatic case of COVID-19 and returns a `201 Created` response.

    Returns a `403 Forbidden` response when trying to notify an already reported case.

    Returns a `429 Too many requests` response when getting more than 5 requests per 5 minutes from
    the same remote host.
    """

    form = NotifyForm(request.form)
    if form.validate():
        # Does not allow to override an already reported case.

        already_exists = models.Case.query                  \
            .filter_by(covid_tracer_id=covid_tracer_id)     \
            .count()

        if already_exists > 0:
            return 'Forbidden', 403

        # Does not allow more than 5 requests per IP per 5 minutes.
        #
        # We allow a reasonable amount of devices from the same address to notify cases in a short
        # period of time as multiple cases can legitimately originate from the same household or
        # organisation.

        if not request.headers.getlist("X-Forwarded-For"):
            remote_addr = request.remote_addr
        else:
            remote_addr = request.headers.getlist("X-Forwarded-For")[0]

        user_agent = request.headers.get('User-Agent')

        five_mins_ago = datetime.datetime.utcnow() - datetime.timedelta(minutes=5)
        prev_reporting_count = models.Request.query                         \
            .filter_by(remote_addr=remote_addr)                             \
            .filter(models.Request.created_at >= five_mins_ago)             \
            .count()

        if prev_reporting_count >= 5:
            return 'Too many requests', 429

        # --

        case = models.Case(
            covid_tracer_id=covid_tracer_id,

            symptoms_onset=form.symptoms_onset.data,
            is_tested=form.is_tested.data,
            comment=form.comment.data,
        )

        req = models.Request(
            remote_addr=remote_addr,
            user_agent=user_agent,
        )

        models.db.session.add(case)
        models.db.session.add(req)
        db.session.commit()

        return 'Created', 201
    else:
        return 'Bad request', 400

if __name__ == '__main__':
    models.db.create_all(app=app)

    app.run()
