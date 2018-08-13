import datetime
import json
import random
import string

from datetime import timedelta
from random import choice

from wtforms import StringField, validators
from wtforms.fields import BooleanField, SubmitField

from flask_wtf import FlaskForm
from flask_mail import Message
from flask import url_for

from wtforms.widgets.html5 import EmailInput
from wtforms.widgets import HiddenInput
from breakfastclub.models import Person, BreadList

from breakfastclub import app, db, mail


class AddPersonForm(FlaskForm):

    name = StringField(
        'name',
        [validators.Length(max=Person.name.property.columns[0].type.length),
         validators.InputRequired()],
    )
    email = StringField(
        'email',
        [validators.Length(max=Person.email.property.columns[0].type.length),
         validators.Email(),
         validators.InputRequired()],
        widget=EmailInput(),
    )


class ShowLoginForm(FlaskForm):
    token = StringField('token', [validators.InputRequired()])

    def validate(self):
        if not super().validate():
            return False
        token = self.token.data
        person = db.session.query(Person).filter_by(token=token).scalar()
        if person is None:
            self.token.errors.append('Invalid token.')
            return False

        self.person = person
        return True


class GenerateBreadListForm(FlaskForm):

    data = StringField('data', widget=HiddenInput())

    def validate(self):
        if not super().validate():
            return False

        try:
            parsed_data = json.loads(self.data.data)
        except ValueError:
            self.data.errors.append('Invalid JSON.')
            return False

        # verify all dates greater than max date in DB.
        # verify all persons exist and active in DB.
        person_ids = [d['person_id'] for d in parsed_data]
        if len(person_ids) != len(set(person_ids)):
            self.data.errors.append('Duplicate person.')
            return False
        people = db.session.query(Person).filter(Person.id.in_(person_ids),
                                                 Person.active == True).all()  # noqa
        if len(people) != len(person_ids):
            self.data.errors.append('Inactive person or invalid person.')
            return False

        dates = [datetime.datetime.strptime(d['date'], '%Y-%m-%d').date()
                 for d in parsed_data]

        qs = db.session.query(BreadList)
        qs = qs.order_by(BreadList.date.desc())
        max_date = qs.first().date
        if not all(date > max_date for date in dates):
            self.data.errors.append('Invalid date.')
            return False

        self.new_breadlist = [BreadList(person_id=p, date=d)
                              for p, d in zip(person_ids, dates)]
        return True

    def save(self):
        db.session.add_all(self.new_breadlist)
        db.session.commit()

    def __init__(self, *args, shuffle=False, **kwargs):

        def find_next_tuesday(date):
            to_add = timedelta(days=(0 - date.weekday()) % 7 + 1)
            return date + to_add

        def find_next_new_tuesday(date):
            r = find_next_tuesday(date)
            while r in existing_future:
                r = find_next_tuesday(r)
            return r

        super().__init__(*args, **kwargs)
        people = db.session.query(Person).filter(Person.active ==  True).all()  # noqa
        today = datetime.date.today()

        # Retrieve each person_id's most recent BreadList
        # as well as existing future dates
        qs = db.session.query(BreadList)
        most_recent = {}
        existing_future = []
        for b in qs:
            if most_recent.setdefault(b.person_id, b.date) < b.date:
                most_recent[b.person_id] = b.date
            if b.date >= today:
                existing_future.append(b.date)
        existing_future = set(existing_future)

        # Put people never before in the list last,
        # and order the rest by most recent bread date
        people = sorted(
            people, key=lambda p: (p.id not in most_recent, most_recent.get(p.id)))
        next_tuesday = find_next_new_tuesday(today)
        self.new_bringers = []
        if shuffle:
            random.shuffle(people)
        for person in people:
            if person.id in most_recent and most_recent[person.id] > today:
                # Skip person who is already on the future list
                continue
            self.new_bringers.append(dict(person=person, person_id=person.id,
                                          date=next_tuesday))
            next_tuesday = find_next_new_tuesday(next_tuesday)
        self.new_bringers = sorted(self.new_bringers, key=lambda p: p['date'],
                                   reverse=True)
        self.data.default = json.dumps(
            [{'person_id': b['person_id'],
              'date': b['date'].strftime('%Y-%m-%d')}
             for b in self.new_bringers]
        )
        self.process()


def generate_token():
    chars = string.ascii_letters + string.digits
    new_token = [choice(chars) for _ in range(64)]
    return ''.join(new_token)


def send_mail_with_token(person):
    external_link = url_for('attempt_login', token=person.token,
                            _external=True)
    subject = "[Breakfastclub] Requested Token"
    body = """Hi {name}
You requested your token for the breakfastclub app.

Click the link below to login.
{link}

Best regards,
The Breakfastclub
"""
    body = body.format(name=person.name, link=external_link)
    email_message = Message(sender=app.config['EMAIL_SENDER'],
                            recipients=[person.email],
                            subject=subject,
                            body=body)
    print(email_message)
    mail.send(email_message)
    return


class TokenManagementFormBase(FlaskForm):

    keys = ['person_name', 'person_email', 'token_link',
            'generate_token', 'email_token']

    def rows(self):
        for person in self.persons:
            yield {k: getattr(self, k + '_' + str(person.id))
                   for k in self.keys}

    def validate(self):
        if not super().validate():
            return False

        requested_token = []
        for person in self.persons:
            if not hasattr(self, 'person_name_' + str(person.id)):
                continue
            person.name = getattr(self, 'person_name_' + str(person.id)).data
            person.email = getattr(self, 'person_email_' + str(person.id)).data

            generate_token_field = getattr(
                self,
                'generate_token_' + str(person.id)
            ).data
            email_token_field = getattr(
                self,
                'email_token_' + str(person.id)
            ).data

            if generate_token_field:
                print("generate new token for {name}".format(name=person.name))
                new_token = generate_token()
                print("{name}'s new token is: {token}".format(name=person.name,
                                                              token=new_token))
                person.token = new_token

            if email_token_field:
                requested_token.append(person)
        db.session.commit()

        for person in requested_token:
            send_mail_with_token(person)
        return True


def get_token_management_form(persons):

    fields = {}
    for person in persons:
        id_str = str(person.id)
        fields['person_name_' + id_str] = StringField(
            default=person.name,
            validators=[validators.InputRequired()],
        )
        fields['person_email_' + id_str] = StringField(
            default=person.email,
            validators=[validators.InputRequired()],
        )
        fields['token_link_' + id_str] = person.token
        fields['generate_token_' + id_str] = BooleanField(default=False)
        fields['email_token_' + id_str] = BooleanField(default=False)

    TokenManagementForm = type('TokenManagementForm',
                               (TokenManagementFormBase,),
                               fields)
    TokenManagementForm.persons = persons
    return TokenManagementForm


class ConfirmEmailNotifyForm(FlaskForm):
    confirm = SubmitField('confirm')
    cancel = SubmitField('cancel')

    def validate(self):
        if not super().validate():
            return False
        if self.cancel.data is True:
            return False

        if self.confirm.data is True:
            return True

        return False
