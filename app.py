from flask import Flask, make_response, redirect, request, Response, render_template, url_for, flash, g, jsonify
from flask_sslify import SSLify
from flask_login import LoginManager, login_required, login_user, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy, Pagination
from flask_mail import Mail, Message
from sqlalchemy import text, and_, exc, func
from database import db_session
from models import User, Store, Campaign, CampaignType, Visitor, AppendedVisitor, Lead
from forms import UserLoginForm, DailyRecapForm
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
login_manager.login_view = "/auth/login"
login_manager.login_message = "Login required to access this site."
login_manager.login_message_category = "primary"

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
        return db_session.query(User).get(int(id))
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
# @app.route('/', methods=['GET'])
@app.route('/index', methods=['GET'])
@login_required
def index():
    """
    The Dashboard View (Default)
    :return: databoxes
    """

    return render_template(
        'index.html',
        current_user=current_user,
        dashboard=get_dashboard(),
        store_name=get_store_name(current_user.store_id),
        today=get_date()
    )


@app.route('/campaigns', methods=['GET'])
@login_required
def campaigns():
    """
    Campaign View
    :return: list campaigns
    """
    archived_count = 0

    # get the list of their stores campaigns
    try:
        campaigns = db_session.query(Campaign).filter(
            Campaign.store_id == current_user.store_id,
            Campaign.status == 'ACTIVE'
        ).all()

        archived_campaigns = db_session.query(Campaign).filter(
            Campaign.store_id == current_user.store_id,
            Campaign.status == 'INACTIVE'
        ).count()

    except exc.SQLAlchemyError as err:
        flash(err, category='danger')
        return redirect(url_for('index'))

    return render_template(
        'campaigns.html',
        current_user=current_user,
        campaigns=campaigns,
        archived_count=archived_campaigns,
        store_name=get_store_name(current_user.store_id),
        today=get_date()
    )


@app.route('/campaign/<int:campaign_pk_id>', methods=['GET'])
@login_required
def campaign_detail(campaign_pk_id):
    """
    The Campaign Detail View
    :return: databoxes
    """
    visitors = []
    visitor_count = 0
    leads = []
    sends = []

    try:
        campaign = db_session.query(Campaign).filter(
            Campaign.store_id == current_user.store_id,
            Campaign.id == campaign_pk_id
        ).one()

    except exc.SQLAlchemyError as err:
        return print(str(err))

    if not campaign:

        # this campaign may not belong to this user
        # redirect and flash a message
        flash('Unauthorized Access.', category='primary')
        return redirect(url_for('index'))

    try:
        visitors = db_session.query(Visitor).filter(
            Visitor.campaign_id == campaign.id,
            Visitor.store_id == current_user.store_id
        ).order_by(Visitor.created_date.desc()).all()

    except exc.SQLAlchemyError as err:
        flash(err, category='danger')
        return redirect(url_for('index'))

    if visitors:
        visitor_count = len(visitors)

    leads = []

    return render_template(
        'campaign_detail.html',
        current_user=current_user,
        campaign=campaign,
        visitors=visitors,
        leads=leads,
        store_name=get_store_name(current_user.store_id),
        today=get_date(),
        visitor_count=visitor_count
    )


@app.route('/campaign/<int:campaign_pk_id>/leads')
@login_required
def get_leads(campaign_pk_id):
    """
    Get the converted leads for the selected campaign
    :param campaign_pk_id:
    :return: list
    """
    leads = None
    lead_count = 0
    campaign = None
    current_time = datetime.datetime.now()
    results = None

    try:
        campaign = db_session.query(Campaign).filter(
            Campaign.id == campaign_pk_id,
            Campaign.store_id == current_user.store_id
        ).one()

    except exc.SQLAlchemyError as err:
        flash(err, category='danger')
        return redirect(url_for('index'))

    if campaign:
        stmt = text('select v.id, av.first_name, av.last_name, av.email, av.home_phone, av.credit_range, '
                    'av.car_year, av.car_model, av.car_make '
                    'from visitors v, appendedvisitors av '
                    'where v.id = av.visitor '
                    'and v.campaign_id = {} '
                    'order by v.id asc'.format(campaign.id))

        results = db_session.query('id', 'first_name', 'last_name', 'email', 'home_phone', 'credit_range',
                                   'car_make', 'car_year', 'car_model').from_statement(stmt).all()

        if results:
            lead_count = len(results)

    return render_template(
        'campaign_leads.html',
        today=get_date(),
        current_user=current_user,
        campaign=campaign,
        results=results,
        lead_count=lead_count,
        store_name=get_store_name(current_user.store_id)
    )


@app.route('/campaign/<int:campaign_pk_id>/emails')
@login_required
def get_emails(campaign_pk_id):
    """
    Get the emails sent to prospects for the selected campaign
    :param campaign_pk_id:
    :return: list
    """

    current_time = datetime.datetime.now()
    results = None
    email_sent_count = 0
    campaign = None

    try:
        campaign = db_session.query(Campaign).filter(
            Campaign.id == campaign_pk_id,
            Campaign.store_id == current_user.store_id
        ).one()

    except exc.SQLAlchemyError as err:
        return print(str(err))

    if campaign:
        stmt = ("select v.id, av.first_name, av.last_name, av.email, av.home_phone, l.followup_email_sent_date, "
                "l.followup_email_receipt_id, l.followup_email_status "
                "from visitors v, appendedvisitors av, leads l "
                "where v.id = av.visitor "
                "and v.campaign_id = {} "
                "and l.followup_email_status = 'SENT' "
                "and l.followup_email_receipt_id is not NULL "
                "and l.followup_email_sent_date is not NULL "
                "order by v.id asc".format(campaign.id))

        results = db_session.query('id', 'first_name', 'last_name', 'email', 'home_phone', 'followup_email_sent_date',
                                   'followup_email_receipt_id', 'followup_email_status').from_statement(stmt).all()

        if results:
            email_sent_count = len(results)

    return render_template(
        'followup_emails.html',
        today=get_date(),
        current_user=current_user,
        campaign=campaign,
        results=results,
        email_sent_count=email_sent_count
    )


@app.route('/campaign/<int:campaign_pk_id>/rvms')
@login_required
def get_rvms(campaign_pk_id):
    """
    Get the list of Ringless Voicemails for the selected campaign
    :param campaign_pk_id:
    :return: list
    """
    rvm_count = 0
    campaign = None

    try:
        campaign = db_session.query(Campaign).filter(
            Campaign.id == campaign_pk_id,
            Campaign.store_id == current_user.store_id
        ).one()

    except exc.SQLAlchemyError as err:
        flash(err, category='danger')
        return redirect(url_for('index'))

    if campaign:
        stmt = ('select v.id, av.first_name, av.last_name, av.email, av.home_phone, l.rvm_status, l.rvm_date, l.rvm_message, '
                'l.rvm_sent '
                'from visitors v, appendedvisitors av, leads l '
                'where v.id = av.visitor '
                'and v.campaign_id = {} '
                'and l.rvm_sent = 1 '
                'and l.rvm_date is not NULL '
                'order by v.id asc'.format(campaign.id))

        results = db_session.query('id', 'first_name', 'last_name', 'email', 'home_phone', 'rvm_status', 'rvm_date',
                                   'rvm_message', 'rvm_sent').from_statement(stmt).all()

        if results:
            rvm_count = len(results)

    return render_template(
        'ringless_voicemail.html',
        today=get_date(),
        current_user=current_user,
        store_name=get_store_name(current_user.store_id),
        campaign=campaign,
        rvm_count=rvm_count,

    )


@app.route('/reports', methods=['GET'])
@login_required
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


@app.route('/reports/daily-recap-report', methods=['GET', 'POST'])
@login_required
def daily_recap_report():
    """
    Return the daily recap report for the store, by date
    :return:
    """
    current_time = datetime.datetime.now()
    form = DailyRecapForm(request.form)
    results = None
    start_date = None
    end_date = None
    results_count = 0
    campaign_name = None

    if request.method == 'POST':
        if 'get-daily-recap' in request.form.keys() and form.validate_on_submit():
            recap_date = form.recap_date.data
            campaign_id = form.campaign_id.data
            start_date = datetime.datetime.strptime(recap_date + ' 00:00:00', '%m/%d/%Y %H:%M:%S')
            end_date = datetime.datetime.strptime(recap_date + ' 23:59:59', '%m/%d/%Y %H:%M:%S')

            # raw sql statement for daily recap report
            stmt = text("select av.created_date, av.first_name, av.last_name, av.address1, av.address2, av.city, "
                        "av.state, av.zip_code, av.zip_4, av.email, av.cell_phone, av.credit_range, av.car_year, "
                        "av.car_make, av.car_model "
                        "from visitors v, appendedvisitors av "
                        "where v.id = av.visitor "
                        "and v.campaign_id = {} "                            
                        "and ( v.created_date between '{}' and '{}' ) "
                        "order by av.last_name, av.first_name asc".format(campaign_id, start_date, end_date))

            # dump the query results to variable
            results = db_session.query('created_date', 'first_name', 'last_name', 'address1', 'address2',
                                       'city', 'state', 'zip_code', 'zip_4', 'email', 'cell_phone', 'credit_range',
                                       'car_year', 'car_make', 'car_model').from_statement(stmt).all()

            if results:
                results_count = len(results)
                campaign_name = db_session.query(Campaign.name).filter(
                    Campaign.id == campaign_id
                ).one()

    return render_template(
        'daily-recap-report.html',
        today=current_time,
        current_user=current_user,
        store_name=get_store_name(current_user.store_id),
        campaigns=get_active_campaigns(current_user.store_id),
        results=results,
        results_count=results_count,
        start_date=start_date,
        end_date=end_date,
        form=form,
        campaign_name=campaign_name
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


@app.route('/login', methods=['GET'])
def login_redirect():
    """
    Redirect to auth/login
    :return: redirect
    """
    return redirect('/auth/login', 302)


@app.route("/auth/login", methods=['GET', 'POST'])
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
        flash('You have been logged in successfully...', 'primary')
        return redirect(request.args.get('next') or url_for('index'))

    return render_template(
        'login.html',
        form=form
    )


@app.route('/logout', methods=['GET'])
@login_required
def logout():
    logout_user()
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
    campaign_count = 0
    visitor_count = 0

    campaign_count = db_session.query(Campaign).filter(
        Campaign.store_id == current_user.store_id,
        Campaign.status == 'ACTIVE'
    ).count()

    visitor_count = db_session.query(Visitor).filter(
        Visitor.store_id == current_user.store_id
    ).count()

    # create dashboard dict
    dashboard = {
        'campaigns': campaign_count,
        'visitors': visitor_count
    }

    # return the dashboard object
    return dashboard


def get_active_campaigns(store_pk_id):
    """
    Get a list of active store campaigns
    :param store_pk_id:
    :return: list
    """

    # get a list of active store campaigns
    campaigns = db_session.query(Campaign).filter(
        Campaign.store_id == store_pk_id,
        Campaign.status == 'ACTIVE'
    ).order_by(Campaign.created_date.desc()).all()

    return campaigns


def get_store_name(store_pk_id):
    """
    Get the name of the store for the
    app and dashboard welcome message
    :param store_pk_id:
    :return: str store_name
    """
    store_name = db_session.query(Store).filter(
        Store.id == store_pk_id
    ).one()

    return str(store_name)


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
