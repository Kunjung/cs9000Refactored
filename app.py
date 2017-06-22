from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_bootstrap import Bootstrap
from flask_login import LoginManager


app = Flask(__name__)

Bootstrap(app)
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


### CONFIGURATION ###
import os
basedir = os.path.abspath(os.path.dirname(__file__))

app.config['WTF_CSRF_ENABLED'] = True
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'data.db')


## database and routes
##1. Database
from flask_login import UserMixin

ratings = db.Table('ratings',
		db.Column('user_id', db.Integer, db.ForeignKey('users.id')),
		db.Column('movie_id', db.Integer, db.ForeignKey('movies.id')),
		db.Column('rating', db.Integer)
	)

ancient_ratings = db.Table('ancient_ratings',
		db.Column('user_id', db.Integer, db.ForeignKey('ancient_users.id')),
		db.Column('movie_id', db.Integer, db.ForeignKey('movies.id')),
		db.Column('rating', db.Float)
	)

class AncientUser(db.Model):
	__tablename__ = 'ancient_users'
	id = db.Column(db.Integer, primary_key=True)
	rated = db.relationship('Movie', secondary=ancient_ratings, backref='ancient_raters', lazy='dynamic')

	def __init__(self, id):
		self.id = id

	def __repr__(self):
		return '<Ancient User %r>' % self.id


class User(UserMixin, db.Model):
	__tablename__ = 'users'
	id = db.Column(db.Integer, primary_key=True)
	username = db.Column(db.String(42), unique=True)
	password = db.Column(db.String(42))
	rated = db.relationship('Movie', secondary=ratings, backref='raters', lazy='dynamic')
	

	def __init__(self, username, password):
		self.username = username
		self.password = password

	def __repr__(self):
		return '<User %r>' % self.username

class Movie(db.Model):
	__tablename__ = 'movies'
	id = db.Column(db.Integer, primary_key=True)
	title = db.Column(db.String(100))
	
	def __init__(self, id, title):
		self.id = id
		self.title = title

	def __repr__(self):
		return '<Movie %r>' % self.title

# use this to update or get data from ratings table
######################
# query = ratings.update().where(
#     ratings.c.user_id == user1.id
# ).where(
#     ratings.c.movie_id == movie1.id
# ).values(rating=new_rating)
#
# db.session.execute(query)
# val = db.session.execute(query).first()[2]




##2. Routes
from flask import render_template, redirect, url_for, request, session

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, IntegerField
from wtforms.validators import InputRequired, Email, Length
from flask_login import login_user, logout_user, login_required, current_user


@login_manager.user_loader
def load_user(user_id):
	return User.query.get(int(user_id))


class LoginForm(FlaskForm):
	username = StringField('Username', validators=[InputRequired(), Length(min=4, max=42)])
	password = PasswordField('Password', validators=[InputRequired(), Length(min=4, max=42)])
	remember = BooleanField('Remember me')

class RegisterForm(FlaskForm):
	email = StringField('Email', validators=[InputRequired(), Email(message='Invalid Email'), Length(max=42)])
	username = StringField('Username', validators=[InputRequired(), Length(min=4, max=42)])
	password = PasswordField('Password', validators=[InputRequired(), Length(min=4, max=42)])

class PreferenceForm(FlaskForm):
	comedy = IntegerField('Comedy', validators=[InputRequired()])
	action = IntegerField('Action', validators=[InputRequired()])
	romance = IntegerField('Romance', validators=[InputRequired()])
	scifi = IntegerField('Scifi', validators=[InputRequired()])

class RatingForm(FlaskForm):
	rating = IntegerField('Rating', validators=[InputRequired()])

@app.route('/')
def home():
	movies = Movie.query.limit(50)
	return render_template('home.html', movies=movies)


@app.route('/login', methods=['GET', 'POST'])
def login():
	form = LoginForm()
	
	if form.validate_on_submit():
		user = User.query.filter_by(username=form.username.data).first()
		if user:
			if user.password == form.password.data:
				login_user(user, remember=form.remember.data)
				return redirect(url_for('dashboard'))
		return '<h1> Wrong username or password </h1>'

	return render_template('login.html', form=form)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
	form = RegisterForm()

	if form.validate_on_submit():
		new_user = User(form.username.data, form.password.data)
		db.session.add(new_user)
		db.session.commit()
		login_user(new_user, remember=True)
		return redirect(url_for('dashboard'))

	return render_template('signup.html', form=form)

@app.route('/secret')	
def secret():
	return render_template('secret.html')
	
import time
@app.route('/dashboard')
@login_required
def dashboard():
	### The collaborative filter will work each time here to get the movie
	### to recommend to the user
	#users = get_all_users()
	#movies = get_all_movies()
	NUM_USER = 16
	users = AncientUser.query.limit(NUM_USER)
	t1 = time.time()
	
	recommended_movies = predict_movies_for_user(current_user, users)
	
	t2 = time.time()

	return render_template('dashboard.html', username=current_user.username, recommended_movies=recommended_movies, time=t2-t1)


@app.route('/rate/<int:movie_id>', methods=['GET', 'POST'])
@login_required
def rate(movie_id):
	global COUNTER

	user_id = current_user.id
	# get user's rating for this movie
	form = RatingForm()
	if form.validate_on_submit():
		rating = float(form.rating.data)
		# update the ratings table and add the rating
		if rating > 5.:
			rating = 5.
		elif rating < 0.:
			rating = 0.
		query = ratings.insert().values(user_id=user_id, movie_id=movie_id, rating=rating)
		db.session.execute(query)
		db.session.commit()
		return redirect(url_for('dashboard'))

	movie = Movie.query.get(movie_id)
	return render_template('rate.html', movie=movie, form=form)


@app.route('/logout')
@login_required
def logout():
	logout_user()
	return redirect(url_for('home'))





#### ML Algorithm ####


THRESHOLD = 0.5
NUMBER_OF_MOVIES_TO_RECOMMEND = 10
THRESHOLD_TO_BEGIN_ALGORITHM = 7


def get_rating_for_ancient_user(user_id, movie_id):
	query = ancient_ratings.select('rating').where(ancient_ratings.c.user_id==user_id).where(ancient_ratings.c.movie_id==movie_id)
	values = db.session.execute(query).first()
	rating = values[2]
	return rating

def get_rating(user_id, movie_id):
	query = ratings.select('rating').where(ratings.c.user_id==user_id).where(ratings.c.movie_id==movie_id)
	values = db.session.execute(query).first()
	rating = values[2]
	return rating

def get_all_users():
	return AncientUser.query.all()

def get_all_movies():
	return Movie.query.all()

# Returns a distance-based similarity score for person1 and person2
def similarity_distance(user1, user2):
	# Get the list of shared_movies
	si={}

	user1_movies = user1.rated
	user2_movies = user2.rated

	sum_of_squares = 0
	for movie in user1_movies:
		if movie in user2_movies:
			si[movie.id]=1

	# if they have no ratings in common, return 0
	if len(si) == 0: return 0

	for movie in user1_movies:
		if movie in user2_movies:
			#Get the ratings for the particular movie
			user1_rating = get_rating(user1.id, movie.id)
			user2_rating = get_rating_for_ancient_user(user2.id, movie.id)

			if user1_rating is None or user2_rating is None:
				continue

			# Add up the squares of all the differences
			diff = user1_rating - user2_rating
			sum_of_squares = sum_of_squares + diff * diff
					
	
	return 1/(1+sum_of_squares)



# Gets recommendations for a person by using a weighted average
# of every other user's rankings

def predict_movies_for_user(user, users):
	totals={}
	simSums={}

	### At the very beginning when the user hasn't rated anything
	if len([movie.id for movie in user.rated]) <= THRESHOLD_TO_BEGIN_ALGORITHM:
		return Movie.query.limit(THRESHOLD_TO_BEGIN_ALGORITHM + 1)

	for other in users:
		# Speed Up by limiting number of movies
		# if len(totals) >= NUMBER_OF_MOVIES_TO_RECOMMEND:
		# 	break

		# don't compare me to myself
		if other.id == user.id: continue

		sim = similarity_distance(user, other)

		# ignore scores less than the threshold
		if sim <= THRESHOLD:
			continue


		for movie in other.rated:
			# only score movies I haven't seen yet
			if movie not in user.rated:

				rating = get_rating_for_ancient_user(other.id, movie.id)
				if rating is None:
					continue
				# Similarity * Score

				totals.setdefault(movie.id ,0)
				totals[movie.id] += rating * sim

				# Sum of similarities
				simSums.setdefault(movie.id ,0)
				simSums[movie.id] += sim

			
	# Create the normalized list
	rankings=[(total/simSums[movie.id], movie_id) for movie_id, total in totals.items()]

	# Return the sorted list
	rankings.sort()
	rankings.reverse()
	movies = [Movie.query.get(id) for ranking, id in rankings]
	return movies















#########################







##### RUN APP #######


import os
if __name__ == '__main__':
	port = int(os.environ.get("PORT", 5000))
	app.run(debug=True, host='0.0.0.0', port=port)