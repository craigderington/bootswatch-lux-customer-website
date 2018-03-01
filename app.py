from flask import Flask, make_response, redirect, request, Response, render_template, url_for, flash, g
from flask_sslify import SSLify
from flask_login import LoginManager, login_required, login_user, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy, Pagination
from sqlalchemy import text, and_, exc, func
from database import db_session
from models import User, Store, Campaign, CampaignType, Visitor, AppendedVisitor, Lead
from forms import UserLoginForm
import config
import datetime
import hashlib
import pymongo
import phonenumbers


# debug
debug = True

# app settings
app = Flask(__name__)
sslify = SSLify(app)

# app config
app.secret_key = config.SECRET_KEY
app.config['MONGO_SERVER'] = config.MONGO_SERVER
app.config['MONGO_DB'] = config.MONGO_DB

# SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = config.SQLALCHEMY_TRACK_MODIFICATIONS
db = SQLAlchemy(app)

# Mongo DB
mongo_client = pymongo.MongoClient(app.config['MONGO_SERVER'], 27017, connect=False)
mongo_db = mongo_client[app.config['MONGO_DB']]

# define our login_manager
login_manager = LoginManager(app)
login_manager.init_app(app)
login_manager.login_view = "/login"

# disable strict slashes
app.url_map.strict_slashes = False


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

        # login the user and redirect
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
    return redirect(url_for('login'))


@app.errorhandler(404)
def page_not_found(err):
    return render_template('error-404.html'), 404


@app.errorhandler(500)
def internal_server_error(err):
    return render_template('error-500.html'), 500


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


def get_store_name(store_pk_id):
    store = db_session.query(Store).get(store_pk_id)
    store_name = str(store.name).encode('utf-8')
    return store_name


def get_date():
    # set the current date time for each page
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
