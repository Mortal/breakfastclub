from flask import Flask, render_template, request
from breakfastclub import app
from breakfastclub.models import Person, Session
import click

@app.route('/')
def index():
    return "Hello, world!"

@app.route('/people')
def show_people():
    session = Session()
    peeps = session.query(Person.name, Person.email)
    return render_template('people.html', people=peeps)

@app.cli.command('initdb')
def initdb_command():
    """Initialize the database."""
    # TODO: fix this. Should be placed somewhere else.
    #people.Base.metadata.create_all(people.engine)
    print("Database initialized")

@app.route('/people/add', methods=['POST', 'GET'])
def add_person():
    if request.method == 'POST':
        name = str(request.form['name'])
        email = str(request.form['email'])
        person = Person(name=name, email=email)
        session = people.Session()
        session.add(person)
        session.commit()
        return render_template('add_person.html')#, person_added=True)
    else:
        return render_template('add_person.html')#, person_added=False)
