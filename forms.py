from flask_wtf import FlaskForm
from wtforms import IntegerField, StringField, PasswordField, DateField, SelectField, RadioField
from wtforms.validators import DataRequired, InputRequired, NumberRange, Length, EqualTo
from wtforms.ext.sqlalchemy.fields import QuerySelectField
from sqlalchemy import text


class UserLoginForm(FlaskForm):
    username = StringField('Username', [DataRequired()])
    password = PasswordField('Password', [DataRequired()])