import os
from flask import Flask, render_template, url_for, redirect, flash, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import click # <<< AÑADIR ESTA LÍNEA

# --- Configuración de la App ---
app = Flask(__name__)
# ¡IMPORTANTE! Necesitas una 'secret_key' para las sesiones y formularios
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'una-clave-secreta-muy-dificil-de-adivinar')

# --- Configuración de la Base de Datos (Aiven) ---
# Usamos una variable de entorno para la URL de Aiven (PostgreSQL o MySQL)
# Como fallback, usamos una base de datos local sqlite para desarrollo.
AIVEN_DB_URI = os.environ.get('AIVEN_DATABASE_URI_PROGRESO')

# --- AÑADIR ESTAS LÍNEAS ---
# Corrección para el dialecto de SQLAlchemy en producción (Render/Aiven)
if AIVEN_DB_URI and AIVEN_DB_URI.startswith("postgres://"):
    AIVEN_DB_URI = AIVEN_DB_URI.replace("postgres://", "postgresql+psycopg2://", 1)
# --- FIN DE LA CORRECCIÓN ---

app.config['SQLALCHEMY_DATABASE_URI'] = AIVEN_DB_URI or 'sqlite:///progreso.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- Configuración de Flask-Login (Autenticación) ---
login_manager = LoginManager(app)
login_manager.login_view = 'login' # Redirige a 'login' si se intenta acceder a una página protegida
login_manager.login_message = 'Debes iniciar sesión para ver esta página.'
login_manager.login_message_category = 'info' # Categoría de mensaje para flash()

# === Modelos de la Base de Datos ===

class User(db.Model, UserMixin):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    
    # Stats del "Juego"
    nivel = db.Column(db.Integer, default=1)
    xp_actual = db.Column(db.Integer, default=0)
    xp_siguiente_nivel = db.Column(db.Integer, default=100)
    monedas = db.Column(db.Integer, default=0)

    # Relaciones (Un usuario tiene muchas misiones, hábitos, etc.)
    misiones = db.relationship('Mision', backref='autor', lazy=True)
    habitos = db.relationship('Habito', backref='autor', lazy=True)
    logros_compartidos = db.relationship('LogroCompartido', backref='autor', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Mision(db.Model):
    __tablename__ = 'mision'
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(200), nullable=False)
    recompensa_xp = db.Column(db.Integer, default=50)
    recompensa_monedas = db.Column(db.Integer, default=10)
    completada = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    pendientes = db.relationship('Pendiente', backref='mision', lazy=True, cascade="all, delete-orphan")

class Pendiente(db.Model):
    __tablename__ = 'pendiente'
    id = db.Column(db.Integer, primary_key=True)
    descripcion = db.Column(db.String(300), nullable=False)
    done = db.Column(db.Boolean, default=False)
    mision_id = db.Column(db.Integer, db.ForeignKey('mision.id'), nullable=False)

class Habito(db.Model):
    __tablename__ = 'habito'
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(200), nullable=False)
    racha = db.Column(db.Integer, default=0)
    recompensa_xp = db.Column(db.Integer, default=10)
    recompensa_monedas = db.Column(db.Integer, default=5)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class TiendaItem(db.Model):
    __tablename__ = 'tienda_item'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    costo = db.Column(db.Integer, nullable=False)
    # Nota: Hacemos la tienda global por simplicidad, no ligada a un usuario.

class LogroCompartido(db.Model):
    __tablename__ = 'logro_compartido'
    id = db.Column(db.Integer, primary_key=True)
    texto = db.Column(db.String(500), nullable=False)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# === Formularios (Flask-WTF) ===

class RegistrationForm(FlaskForm):
    username = StringField('Usuario', validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField('Contraseña', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirmar Contraseña', validators=[DataRequired(), EqualTo('password', message='Las contraseñas deben coincidir.')])
    submit = SubmitField('Registrarse')

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Contraseña', validators=[DataRequired()])
    submit = SubmitField('Iniciar Sesión')

class MisionForm(FlaskForm):
    titulo = StringField('Título de la Misión', validators=[DataRequired(), Length(max=200)])
    submit = SubmitField('Crear Misión')

class HabitoForm(FlaskForm):
    titulo = StringField('Título del Hábito', validators=[DataRequired(), Length(max=200)])
    submit = SubmitField('Crear Hábito')

class ShareLogroForm(FlaskForm):
    texto = TextAreaField('Comparte tu logro...', validators=[DataRequired(), Length(min=1, max=500)])
    submit = SubmitField('Publicar')

# === Rutas de Autenticación ===

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=True)
            return redirect(url_for('index'))
        else:
            flash('Login fallido. Revisa tu email y contraseña.', 'danger')
    return render_template('login.html', title='Iniciar Sesión', form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_password = generate_password_hash(form.password.data)
        user = User(username=form.username.data, email=form.email.data, password_hash=hashed_password)
        db.session.add(user)
        try:
            db.session.commit()
            flash('¡Tu cuenta ha sido creada! Ya puedes iniciar sesión.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            flash('Error al registrar. El email o usuario ya existe.', 'danger')
            app.logger.error(f"Error en registro: {e}")
            
    return render_template('register.html', title='Registrarse', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# === Rutas de la Aplicación ===

@app.route('/')
@login_required
def index():
    """Ruta principal: El Panel Central (Dashboard)."""
    stats = current_user
    xp_percent = (stats.xp_actual / stats.xp_siguiente_nivel) * 100
    
    misiones_urgentes = Mision.query.filter_by(user_id=stats.id, completada=False).limit(2).all()
    habitos_diarios = Habito.query.filter_by(user_id=stats.id).limit(3).all()
    
    return render_template(
        'index.html',
        title='Panel Central',
        stats=stats,
        xp_percent=xp_percent,
        misiones=misiones_urgentes,
        habitos=habitos_diarios
    )

@app.route('/misiones', methods=['GET', 'POST'])
@login_required
def misiones():
    """Página para ver y crear Misiones (Metas y Proyectos)."""
    form = MisionForm()
    if form.validate_on_submit():
        nueva_mision = Mision(
            titulo=form.titulo.data,
            autor=current_user
        )
        db.session.add(nueva_mision)
        db.session.commit()
        flash('¡Misión creada!', 'success')
        return redirect(url_for('misiones'))
        
    lista_misiones = Mision.query.filter_by(user_id=current_user.id).all()
    return render_template(
        'misiones.html',
        title='Misiones',
        misiones=lista_misiones,
        form=form
    )

@app.route('/habitos', methods=['GET', 'POST'])
@login_required
def habitos():
    """Página para gestionar los Hábitos."""
    form = HabitoForm()
    if form.validate_on_submit():
        nuevo_habito = Habito(
            titulo=form.titulo.data,
            autor=current_user
        )
        db.session.add(nuevo_habito)
        db.session.commit()
        flash('¡Hábito creado!', 'success')
        return redirect(url_for('habitos'))

    lista_habitos = Habito.query.filter_by(user_id=current_user.id).all()
    return render_template(
        'habitos.html',
        title='Hábitos',
        habitos=lista_habitos,
        form=form
    )

@app.route('/tienda', methods=['GET', 'POST'])
@login_required
def tienda():
    """Página de La Tienda (Recompensas)."""
    # En una app real, aquí tendrías un formulario para "comprar"
    # Por ahora, solo mostramos los items.
    
    # --- ELIMINAR ESTE BLOQUE ---
    # Si la tienda está vacía, añadimos items de ejemplo
    # if TiendaItem.query.count() == 0:
    #     db.session.add_all([
    #         TiendaItem(nombre="1h de Videojuegos", costo=50),
    #         TiendaItem(nombre="Cena especial (delivery)", costo=150),
    #         TiendaItem(nombre="Día libre de tareas", costo=300)
    #     ])
    #     db.session.commit()
    # --- FIN DEL BLOQUE ELIMINADO ---

    items_tienda = TiendaItem.query.all()
    
    return render_template(
        'tienda.html',
        title='Tienda',
        tienda=items_tienda,
        monedas_usuario=current_user.monedas
    )

@app.route('/perfil')
@login_required
def perfil():
    """Página de Perfil y Estadísticas detalladas."""
    # Aquí podríamos añadir más estadísticas, logros, etc.
    return render_template(
        'perfil.html',
        title='Mi Perfil',
        stats=current_user
    )

@app.route('/feed', methods=['GET', 'POST'])
@login_required
def feed():
    """Página social para compartir y ver logros."""
    form = ShareLogroForm()
    if form.validate_on_submit():
        logro = LogroCompartido(
            texto=form.texto.data,
            autor=current_user
        )
        db.session.add(logro)
        db.session.commit()
        flash('¡Logro compartido!', 'success')
        return redirect(url_for('feed'))
        
    # Mostramos los 20 logros más recientes de todos los usuarios
    logros_publicos = LogroCompartido.query.order_by(LogroCompartido.timestamp.desc()).limit(20).all()
    
    return render_template(
        'feed.html',
        title='Feed de Logros',
        form=form,
        logros=logros_publicos
    )

# === Rutas de Acciones (Completar, Comprar, etc.) ===
# Estas rutas procesan lógica (POST) y luego redirigen

@app.route('/completar_habito/<int:habito_id>', methods=['POST'])
@login_required
def completar_habito(habito_id):
    habito = Habito.query.get_or_404(habito_id)
    if habito.autor != current_user:
        return redirect(url_for('habitos')) # No es su hábito

    # Lógica del juego
    current_user.xp_actual += habito.recompensa_xp
    current_user.monedas += habito.recompensa_monedas
    habito.racha += 1
    
    # Lógica de subir de nivel (simplificada)
    if current_user.xp_actual >= current_user.xp_siguiente_nivel:
        current_user.nivel += 1
        current_user.xp_actual -= current_user.xp_siguiente_nivel
        current_user.xp_siguiente_nivel = int(current_user.xp_siguiente_nivel * 1.5) # Dificultad incremental
        flash(f'¡Felicidades, subiste al Nivel {current_user.nivel}!', 'success')

    db.session.commit()
    flash('¡Hábito completado!', 'info')
    return redirect(url_for('habitos'))

# --- REEMPLAZAR EL BLOQUE __main__ CON ESTO ---

# === Comandos CLI para la App ===
@app.cli.command("init-db")
def init_db_command():
    """Limpia la BD existente y crea nuevas tablas."""
    # Opcional: db.drop_all() si quieres borrar todo en cada build
    # Advertencia: ¡esto borrará todos los datos!
    # db.drop_all() 
    
    db.create_all()
    
    # Añadir items de tienda solo si no existen
    if TiendaItem.query.count() == 0:
        db.session.add_all([
            TiendaItem(nombre="1h de Videojuegos", costo=50),
            TiendaItem(nombre="Cena especial (delivery)", costo=150),
            TiendaItem(nombre="Día libre de tareas", costo=300)
        ])
        db.session.commit()
    
    print("Base de datos inicializada y poblada.")

# --- Ejecución de la App ---
# El bloque if __name__ == '__main__': se elimina.
# El servidor de producción (Gunicorn) llamará al objeto 'app' directamente.
# Para desarrollo local, ahora se debe usar:
# 1. export FLASK_APP=app.py
# 2. export FLASK_DEBUG=1
# 3. flask init-db (solo la primera vez)
# 4. flask run
# --- FIN DEL REEMPLAZO ---