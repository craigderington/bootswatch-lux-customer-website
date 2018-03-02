from flask import Flask, make_response, redirect, request, Response, render_template, url_for, flash, g, jsonify
from flask_sslify import SSLify
from flask_login import LoginManager, login_required, login_user, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy, Pagination
from flask_mail import Mail, Message
from sqlalchemy import text, and_, exc, func
from database import db_session
from models import User, Store, Campaign, CampaignType, Visitor, AppendedVisitor, Lead
from forms import UserLoginForm
from celery import Celery
import config
import datetime
import hashlib
import phonenumbers
import random
import time
import os


# debug
debug = True

# app settings
app = Flask(__name__)
sslify = SSLify(app)

# app config
app.secret_key = config.SECRET_KEY
# app.config['MONGO_SERVER'] = config.MONGO_SERVER
# app.config['MONGO_DB'] = config.MONGO_DB

# Flask-Mail configuration
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = config.MAIL_USERNAME
app.config['MAIL_PASSWORD'] = config.MAIL_PASSWORD
app.config['MAIL_DEFAULT_SENDER'] = config.MAIL_DEFAULT_SENDER

# SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = config.SQLALCHEMY_TRACK_MODIFICATIONS
db = SQLAlchemy(app)

# define our login_manager
login_manager = LoginManager(app)
login_manager.init_app(app)
login_manager.login_view = "/login"

# disable strict slashes
app.url_map.strict_slashes = False

# Celery config
app.config['CELERY_BROKER_URL'] = config.CELERY_BROKER_URL
app.config['CELERY_RESULT_BACKEND'] = config.CELERY_RESULT_BACKEND
app.config['CELERY_ACCEPT_CONTENT'] = config.CELERY_ACCEPT_CONTENT
app.config.update(accept_content=['json', 'pickle'])
# Initialize Celery
celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)

# Config mail
mail = Mail(app)


# clear all db sessions at the end of each request
@app.teardown_appcontext
def shutdown_session(exception=None):
    db_session.remove()


# load the user
@login_manager.user_loader
def load_user(id):
    try:
        return db_session.query(User).get_id(int(id))
    except exc.SQLAlchemyError as err:
        return None


# run before each request
@app.before_request
def before_request():
    g.user = current_user


# tasks sections, for async functions, etc...
@celery.task(serializer='pickle')
def send_async_email(msg):
    """Background task to send an email with Flask-Mail."""
    with app.app_context():
        mail.send(msg)


@celery.task(bind=True)
def long_task(self):
    """Background task that runs a long function with progress reports."""
    verb = ['Starting up', 'Booting', 'Repairing', 'Loading', 'Checking']
    adjective = ['master', 'radiant', 'silent', 'harmonic', 'fast']
    noun = ['solar array', 'particle reshaper', 'cosmic ray', 'orbiter', 'bit']
    message = ''
    total = random.randint(10, 50)
    for i in range(total):
        if not message or random.random() < 0.25:
            message = '{0} {1} {2}...'.format(random.choice(verb),
                                              random.choice(adjective),
                                              random.choice(noun))
        self.update_state(state='PROGRESS',
                          meta={'current': i, 'total': total,
                                'status': message})
        time.sleep(1)
    return {'current': 100, 'total': 100, 'status': 'Task completed!',
            'result': 42}


# default routes
@app.route('/', methods=['GET'])
@app.route('/index', methods=['GET'])
#@login_required
def index():
    """
    The Dashboard View (Default)
    :return: databoxes
    """

    return render_template(
        'index.html',
        current_user=current_user,
        dashboard=get_dashboard(),
        today=get_date()
    )


@app.route('/campaigns', methods=['GET'])
#@login_required
def campaigns():
    """
    Campaign View
    :return: list campaigns
    """

    # get the list of their stores campaigns
    campaigns = []

    return render_template(
        'campaigns.html',
        current_user=current_user,
        campaigns=campaigns,
        today=get_date()
    )


@app.route('/visitors', methods=['GET'])
#@login_required
def visitors():
    """
    The Campaign Visitor View
    :return: databoxes
    """
    visitors = []

    return render_template(
        'visitors.html',
        current_user=current_user,
        visitors=visitors,
        today=get_date()
    )


@app.route('/leads', methods=['GET'])
#@login_required
def leads():
    """
    The Campaign Lead View
    :return: list leads
    """
    leads = []

    return render_template(
        'leads.html',
        current_user=current_user,
        leads=leads,
        today=get_date()
    )


@app.route('/reports', methods=['GET'])
#@login_required
def reports():
    """
    The Campaign Report View
    :return: databoxes
    """

    return render_template(
        'reports.html',
        current_user=current_user,
        today=get_date()
    )


def send_email(to, subject, **kwargs):
    """
    Send Mail function
    :param to:
    :param subject:
    :param template:
    :param kwargs:
    :return: celery async task id
    """
    msg = Message(
        subject,
        sender=app.config['MAIL_DEFAULT_SENDER'],
        recipients=[to, ]
    )
    msg.body = "EARL Dealer Demo UI Test"
    # msg.html = render_template(template + '.html', **kwargs)
    send_async_email.delay(msg)


@app.route('/longtask', methods=['POST'])
def longtask():
    task = long_task.apply_async()
    return jsonify({}), 202, {'Location': url_for('taskstatus',
                                                  task_id=task.id)}


@app.route("/login", methods=['GET', 'POST'])
def login():

    form = UserLoginForm()

    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data

        user = db_session.query(User).filter_by(username=username).first()

        if user is None or not user.check_password(password):
            flash('Username or password is invalid!  Please try again...')
            return redirect(url_for('login'))

        # login the user and redirect, note the next param
        login_user(user)
        flash('You have been logged in successfully...', 'success')
        return redirect(request.args.get('next') or url_for('index'))

    return render_template(
        'login.html',
        form=form
    )


@app.route('/logout', methods=['GET'])
@login_required
def logout():
    logout_user()
    flash('You have been logged out successfully', category='success')
    return redirect(url_for('index'))


@app.errorhandler(404)
def page_not_found(err):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_server_error(err):
    return render_template('500.html'), 500


def flash_errors(form):
    for field, errors in form.errors.items():
        for error in errors:
            flash(u"Error in the %s field - %s" % (
                getattr(form, field).label.text,
                error
            ))


def get_dashboard():
    """
    Get the dashboard data
    :return: dict
    """

    dashboard = {}
    return dashboard


def get_date():
    """
    Set the datetime stamp for the layout template context
    :return: datetime str
    """
    today = datetime.datetime.now().strftime('%c')
    return '{}'.format(today)


@app.template_filter('formatdate')
def format_date(value):
    dt = value
    return dt.strftime('%Y-%m-%d %H:%M')


@app.template_filter('datemdy')
def format_date(value):
    dt = value
    return dt.strftime('%m/%d/%Y')


if __name__ == '__main__':

    port = 8880

    # start the application
    app.run(
        debug=debug,
        port=port
    )
