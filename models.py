import datetime

from app import db

class Case(db.Model):
    __tablename__ = 'cases'

    # The unique CovidTracer app ID.
    covid_tracer_id = db.Column(db.String(length=8), primary_key=True)

    created_at = db.Column(
        db.DateTime(), nullable=False, index=True, default=datetime.datetime.utcnow
    )

    symptoms_date = db.Column(db.Date(), nullable=False)
    tested = db.Column(db.Boolean(), nullable=False) # Has it been tested against Covid-19?
    comment = db.Column(db.String(1000))

    # Information about the notifying device.
    remote_addr = db.Column(db.String, nullable=False, index=True)
    user_agent = db.Column(db.String, nullable=True)
