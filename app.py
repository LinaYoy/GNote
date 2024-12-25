from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from werkzeug.exceptions import abort
from sqlalchemy.exc import IntegrityError
from datetime import datetime
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from models import db, User, Category, Note

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key_here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.before_request
def create_tables():
    db.create_all()

@app.route('/')
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    categories = Category.query.filter_by(user_id=current_user.id).all()
    return render_template('index.html', categories=categories)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first() is not None:
            flash('Пользователь с таким именем уже существует.')
            return redirect(url_for('register'))
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError as e:
            db.session.rollback()
            flash(f'Произошла ошибка при регистрации: {str(e)}')
            return redirect(url_for('register'))
        flash('Вы успешно зарегистрированы!')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user is None or not user.check_password(password):
            flash('Неверное имя пользователя или пароль.')
            return redirect(url_for('login'))
        login_user(user)
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        old_password = request.form['old_password']
        new_password = request.form['new_password']
        confirm_new_password = request.form['confirm_new_password']
        if not current_user.check_password(old_password):
            flash('Неверный текущий пароль.')
            return redirect(url_for('settings'))
        if new_password != confirm_new_password:
            flash('Новые пароли не совпадают.')
            return redirect(url_for('settings'))
        current_user.set_password(new_password)
        db.session.commit()
        flash('Пароль успешно изменён.')
        return redirect(url_for('settings'))
    return render_template('settings.html')

@app.route('/create_category', methods=['POST'])
@login_required
def create_category():
    category_name = request.form['category_name']
    category = Category(name=category_name, user_id=current_user.id)
    db.session.add(category)
    try:
        db.session.commit()
    except IntegrityError as e:
        db.session.rollback()
        flash(f'Категория с таким именем уже существует: {str(e)}')
        return redirect(url_for('index'))
    flash('Категория создана.')
    return redirect(url_for('index'))

@app.route('/delete_category/<int:category_id>', methods=['POST'])
@login_required
def delete_category(category_id):
    category = Category.query.get_or_404(category_id)
    if category.user_id != current_user.id:
        abort(403)
    db.session.delete(category)
    db.session.commit()
    flash('Категория удалена.')
    return redirect(url_for('index'))

@app.route('/add_note', methods=['POST'])
@login_required
def add_note():
    note_content = request.form['note']
    category_id = request.form['category_id']  # Получаем category_id из формы
    note = Note(content=note_content, category_id=category_id, user_id=current_user.id)
    db.session.add(note)
    db.session.commit()
    send_note_to_telegram(note.content)
    flash('Заметка успешно отправлена!')
    return redirect(url_for('show_notes', category_id=category_id))

@app.route('/notes')
@login_required
def all_notes():
    notes = Note.query.filter_by(user_id=current_user.id).order_by(Note.id.desc()).all()
    return render_template('all_notes.html', notes=notes)  # Предположим, что у вас есть шаблон all_notes.html

@app.route('/notes/<int:category_id>')
@login_required
def show_notes(category_id):
    category = Category.query.get_or_404(category_id)
    if category.user_id != current_user.id:
        abort(403)
    notes = Note.query.filter_by(category_id=category_id).order_by(Note.id.desc()).all()
    return render_template('notes.html', notes=notes, category=category)

@app.route('/edit_note/<int:note_id>', methods=['GET', 'POST'])
@login_required
def edit_note(note_id):
    note = Note.query.get_or_404(note_id)
    if note.user_id != current_user.id:
        abort(403)
    if request.method == 'POST':
        note.content = request.form['content']
        db.session.commit()
        flash('Заметка успешно обновлена!')
        return redirect(url_for('show_notes', category_id=note.category_id))
    return render_template('edit_note.html', note=note)

@app.route('/delete_note/<int:note_id>', methods=['POST'])
@login_required
def delete_note(note_id):
    note = Note.query.get_or_404(note_id)
    if note.user_id != current_user.id:
        abort(403)
    db.session.delete(note)
    db.session.commit()
    flash('Заметка удалена.')
    return redirect(url_for('show_notes', category_id=note.category_id))

def send_note_to_telegram(text):
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    data = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': text
    }
    response = requests.post(url, json=data)
    print(response.json())

if __name__ == '__main__':
    app.run(debug=True)