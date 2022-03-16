import json
import os
import sqlite3
import httpagentparser
from geopy.geocoders import Nominatim
import datetime

from flask import Flask, redirect, request, url_for
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)

from oauthlib.oauth2 import WebApplicationClient
import requests

from db import init_db_command
from user import User

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", None)
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", None)
user_agent = os.environ.get('user_agent', None)
API_KEY = os.environ.get("API_KEY", None)
GOOGLE_DISCOVERY_URL = ("https://accounts.google.com/.well-known/openid-configuration")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(24)

login_manager = LoginManager()
login_manager.init_app(app)

try:
    init_db_command()
except sqlite3.OperationalError:
    pass # Assume it's already been created

client = WebApplicationClient(GOOGLE_CLIENT_ID)

@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

@app.route("/")
def index():
    if current_user.is_authenticated:
        return (
            "<p>Hello, {}! You're logged in! Email: {}</p>"
            "<div><p>Google Profile Picture:</p>"
            '<img src="{}" alt="Google profile pic"></img></div>'
            '<p><a class="button" href="/logout">Logout</a></p>'
            '<p><a class="button" href="/about">Info about login</a></p>'
            '<p><a class="button" href="/useragent">Info about OS and Browser</a></p>'
            '<p><a class="button" href="/list/">Weather for 7 days</a></p>'
            '<p><a class="button" href="/weather/">Weather on a particular day</a></p>'.format(
                current_user.name, current_user.email, current_user.profile_pic
            )
        )
    else:
        return '<a class="button" href="/login">Google Login</a>'

def get_google_provider_cfg():
    return requests.get(GOOGLE_DISCOVERY_URL).json()

@app.route("/login")
def login():
    google_provider_cfg = get_google_provider_cfg()
    authorization_endpoint = google_provider_cfg["authorization_endpoint"]

    request_uri = client.prepare_request_uri(
        authorization_endpoint,
        redirect_uri=request.base_url + "/callback",
        scope=["openid", "email", "profile"],
    )
    return redirect(request_uri)


@app.route("/login/callback")
def callback():
    code = request.args.get("code")

    google_provider_cfg = get_google_provider_cfg()
    token_endpoint = google_provider_cfg["token_endpoint"]

    token_url, headers, body = client.prepare_token_request(
        token_endpoint,
        authorization_response=request.url,
        redirect_url=request.base_url,
        code=code,
    )

    token_response = requests.post(
        token_url,
        headers=headers,
        data=body,
        auth=(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET),
    )

    client.parse_request_body_response(json.dumps(token_response.json()))

    userinfo_endpoint = google_provider_cfg["userinfo_endpoint"]
    uri, headers, body = client.add_token(userinfo_endpoint)
    userinfo_response = requests.get(uri, headers=headers, data=body)

    if userinfo_response.json().get("email_verified"):
        unique_id = userinfo_response.json()["sub"]
        users_email = userinfo_response.json()["email"]
        picture = userinfo_response.json()["picture"]
        users_name = userinfo_response.json()["given_name"]
    else:
        return "User email not available or not verified by Google.", 400

    user = User(
        id_=unique_id, name=users_name, email=users_email, profile_pic=picture
    )

    if not User.get(unique_id):
        User.create(unique_id, users_name, users_email, picture)

    login_user(user)

    return redirect(url_for("index"))

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))

@app.route("/about")
def about():
    #if current_user.is_authenticated:
        return (
            "<p>Name: {}</p>"
            "<p>Email: {}</p>"
            "<div><p>Google Profile Picture:</p>"
            '<img src="{}" alt="Google profile pic"></img></div>'.format(
                current_user.name, current_user.email, current_user.profile_pic
            )
        )
    # else:
    #     return '<p>Login first, please.</p>'

@app.route("/useragent")
def useragent():
    agent = request.environ.get('HTTP_USER_AGENT')
    browser = httpagentparser.detect(agent)
    if not browser:
        browser = agent.split('/')[0]
    else:
        browser = browser['browser']['name']
    return (
        '<p>OS name: {}</p>'
        '<p>Browser: {}</p>'.format(os.name, browser)
    )

@app.route("/list/")
def input_city():
    return ('<p><strong>Please, input name city in URL, for ex.:</strong></p>'
            '<p>https://127.0.0.1:5000/list/<strong>minsk</strong></p>')

@app.route("/list/<city>")
def weather_week(city):
    geolocator = Nominatim(user_agent=user_agent)
    location = geolocator.geocode(city)
    lat = location.latitude
    long = location.longitude
    weather_req = requests.get('https://api.openweathermap.org/data/2.5/onecall?lat={}&lon={}&appid={}'.format(lat, long, API_KEY))
    daily_weather = json.loads(weather_req.text)['daily']
    review=('<h1>Weather in {}</h1>'
            '<h2>for the next 7 days</h2>').format(city)
    for i in range(7):
        temp = round(daily_weather[i]['temp']['day'] - 273.15)
        feels_like = round(daily_weather[i]['feels_like']['day'] - 273.15)
        clouds = daily_weather[i]['clouds']
        wind_speed = daily_weather[i]['wind_speed']

        review += '<p>{} day: temperature - {}, feels like {}, cloudness - {}%, wind speed - {}m/s</p>'.format(str(i+1),
                str(temp), str(feels_like), str(clouds), str(wind_speed))
    return review

@app.route("/weather/")
def input_city_date():
    return ('<p><strong>Please, input name city and date in URL, for ex.:</strong></p>'
            '<p>https://127.0.0.1:5000/<s>weather/</s><strong>minsk/15-03-2022</strong></p>'
            '<p>You can find information for the last 5 days only.</p>')


@app.route("/<city>/<date>")
def weather_date(city, date):
    geolocator = Nominatim(user_agent=user_agent)
    location = geolocator.geocode(city)
    lat = location.latitude
    long = location.longitude
    timest = datetime.datetime.strptime(date, "%d-%m-%Y").timestamp()
    weather_req = requests.get('http://api.openweathermap.org/data/2.5/onecall/timemachine?lat={}&lon={}&dt={}&appid={}'.format(lat, long, int(timest), API_KEY))
    current_weather = json.loads(weather_req.text)['current']
    review = ('<h1>Weather in {}</h1>'
              '<h2>{}</h2>').format(city, date)
    temp = round(current_weather['temp'] - 273.15)
    feels_like = round(current_weather['feels_like'] - 273.15)
    clouds = current_weather['clouds']
    wind_speed = current_weather['wind_speed']

    review += '<p>temperature - {}, feels like {}, cloudness - {}%, wind speed - {}m/s</p>'.format(
        str(temp), str(feels_like), str(clouds), str(wind_speed))
    return review

if __name__ == "__main__":
    app.run(ssl_context="adhoc")