import os
import locale
from flask import Flask, render_template, url_for, redirect, flash, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, TextAreaField, IntegerField, SelectField
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import click

# --- Configuración de la App ---
app = Flask(__name__)
# ¡IMPORTANTE! Necesitas una 'secret_key' para las sesiones y formularios
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'una-clave-secreta-muy-dificil-de-adivinar')

# --- Configuración de la Base de Datos (Aiven) ---
# Usamos una variable de entorno para la URL de Aiven (PostgreSQL o MySQL)
AIVEN_DB_URI = os.environ.get('AIVEN_DATABASE_URI_PROGRESO')

if AIVEN_DB_URI and AIVEN_DB_URI.startswith("postgres://"):
    # Corregir el dialecto para Render/psycopg2
    AIVEN_DB_URI = AIVEN_DB_URI.replace("postgres://", "postgresql+psycopg2://", 1)
    
app.config['SQLALCHEMY_DATABASE_URI'] = AIVEN_DB_URI or 'sqlite:///progreso.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- Configuración de Flask-Login (Autenticación) ---
login_manager = LoginManager(app)
login_manager.login_view = 'login' # Redirige a 'login' si se intenta acceder a una página protegida
login_manager.login_message = 'Debes iniciar sesión para ver esta página.'
login_manager.login_message_category = 'info' # Categoría de mensaje para flash()

# === Modelos de la Base de Datos (Actualizados) ===

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
    pesos = db.Column(db.Integer, default=10000) # Empezar con 10.000 COP
    vida = db.Column(db.Integer, default=100) # Vida (HP) en %

    # Relaciones (Un usuario tiene muchas áreas, misiones, hábitos, etc.)
    areas = db.relationship('AreaVida', backref='autor', lazy=True, cascade="all, delete-orphan")
    misiones = db.relationship('Mision', backref='autor', lazy=True, cascade="all, delete-orphan")
    habitos = db.relationship('Habito', backref='autor', lazy=True, cascade="all, delete-orphan")
    logros_compartidos = db.relationship('LogroCompartido', backref='autor', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def ajustar_vida(self, cantidad):
        """Ajusta la vida, asegurando que se mantenga entre 0 y 100."""
        self.vida = max(0, min(100, self.vida + cantidad))

# NUEVO: Modelo de Áreas de Vida
class AreaVida(db.Model):
    __tablename__ = 'area_vida'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    icono_svg = db.Column(db.String(100), nullable=False, default='M12 21a9 9 0 01-9-9 9 9 0 019-9 9 9 0 019 9 9 9 0 01-9 9z') # Icono por defecto (círculo)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # Relaciones (Un área tiene muchas misiones y hábitos)
    misiones = db.relationship('Mision', backref='area', lazy=True)
    habitos = db.relationship('Habito', backref='area', lazy=True)

class Mision(db.Model):
    __tablename__ = 'mision'
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(200), nullable=False)
    recompensa_xp = db.Column(db.Integer, default=50)
    recompensa_pesos = db.Column(db.Integer, default=5000) # Recompensa en COP
    completada = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    area_id = db.Column(db.Integer, db.ForeignKey('area_vida.id'), nullable=True) # Puede ser nulo
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
    recompensa_pesos = db.Column(db.Integer, default=1000) # Recompensa en COP
    penalizacion_vida = db.Column(db.Integer, default=5) # Daño a la vida (HP) si se falla
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    area_id = db.Column(db.Integer, db.ForeignKey('area_vida.id'), nullable=True) # Puede ser nulo

class TiendaItem(db.Model):
    __tablename__ = 'tienda_item'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    costo_pesos = db.Column(db.Integer, nullable=False) # Costo en COP

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

# NUEVO: Formulario para crear Áreas de Vida
class AreaVidaForm(FlaskForm):
    # Lista de iconos predefinidos de Heroicons (https://heroicons.com/)
    ICONOS = [
        ('icono-salud', 'Salud (Corazón)'),
        ('icono-finanzas', 'Finanzas (Moneda)'),
        ('icono-trabajo', 'Trabajo (Maletín)'),
        ('icono-estudio', 'Estudio (Libro)'),
        ('icono-personal', 'Personal (Persona)'),
        ('icono-social', 'Social (Grupo)'),
        ('icono-default', 'General (Estrella)')
    ]
    nombre = StringField('Nombre del Área', validators=[DataRequired(), Length(max=100)])
    icono = SelectField('Icono', choices=ICONOS, validators=[DataRequired()])
    submit = SubmitField('Crear Área')

class MisionForm(FlaskForm):
    titulo = StringField('Título de la Misión', validators=[DataRequired(), Length(max=200)])
    recompensa_xp = IntegerField('Recompensa XP', default=50, validators=[NumberRange(min=0)])
    recompensa_pesos = IntegerField('Recompensa Pesos (COP)', default=5000, validators=[NumberRange(min=0)])
    area = SelectField('Área de Vida', coerce=int)
    submit = SubmitField('Crear Misión')

class HabitoForm(FlaskForm):
    titulo = StringField('Título del Hábito', validators=[DataRequired(), Length(max=200)])
    recompensa_xp = IntegerField('Recompensa XP', default=10, validators=[NumberRange(min=0)])
    recompensa_pesos = IntegerField('Recompensa Pesos (COP)', default=1000, validators=[NumberRange(min=0)])
    penalizacion_vida = IntegerField('Penalización HP (si fallas)', default=5, validators=[NumberRange(min=0)])
    area = SelectField('Área de Vida', coerce=int)
    submit = SubmitField('Crear Hábito')

class ShareLogroForm(FlaskForm):
    texto = TextAreaField('Comparte tu logro...', validators=[DataRequired(), Length(min=1, max=500)])
    submit = SubmitField('Publicar')
    
# === Filtros de Jinja (para formato de moneda) ===
@app.template_filter('format_pesos')
def format_pesos(valor):
    """Formatea un número como pesos colombianos."""
    try:
        # Intentar establecer la localización colombiana
        locale.setlocale(locale.LC_ALL, 'es_CO.UTF-8')
    except locale.Error:
        # Fallback si 'es_CO.UTF-8' no está disponible en el servidor
        locale.setlocale(locale.LC_ALL, '')
    
    try:
        # 'c' es para formato de moneda local
        return locale.format_string("%d", valor, grouping=True)
    except Exception:
        return str(valor) # Fallback simple

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
        user = User(
            username=form.username.data, 
            email=form.email.data, 
            password_hash=hashed_password
        )
        db.session.add(user)
        try:
            db.session.commit()
            
            # Crear áreas por defecto para el nuevo usuario
            area_personal = AreaVida(nombre="Personal", icono_svg='icono-personal', autor=user)
            area_trabajo = AreaVida(nombre="Trabajo", icono_svg='icono-trabajo', autor=user)
            area_salud = AreaVida(nombre="Salud", icono_svg='icono-salud', autor=user)
            db.session.add_all([area_personal, area_trabajo, area_salud])
            db.session.commit()
            
            flash('¡Tu cuenta ha sido creada! Áreas por defecto añadidas.', 'success')
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

# === Rutas de la Aplicación (Actualizadas) ===

@app.route('/')
@login_required
def index():
    """Ruta principal: El Panel Central (Dashboard)."""
    stats = current_user
    xp_percent = (stats.xp_actual / stats.xp_siguiente_nivel) * 100
    
    # Obtenemos las áreas del usuario, cargando sus misiones y hábitos
    # Esto es más eficiente que hacer queries separadas
    areas_usuario = AreaVida.query.filter_by(user_id=stats.id).all()
    
    return render_template(
        'index.html',
        title='Panel Central',
        stats=stats,
        xp_percent=xp_percent,
        areas=areas_usuario # Pasamos las áreas al template
    )

# NUEVA RUTA para gestionar Áreas de Vida
@app.route('/areas', methods=['GET', 'POST'])
@login_required
def areas():
    """Página para crear y ver las Áreas de Vida."""
    form = AreaVidaForm()
    if form.validate_on_submit():
        nueva_area = AreaVida(
            nombre=form.nombre.data,
            icono_svg=form.icono.data,
            autor=current_user
        )
        db.session.add(nueva_area)
        db.session.commit()
        flash('¡Área de Vida creada!', 'success')
        return redirect(url_for('areas'))
        
    lista_areas = AreaVida.query.filter_by(user_id=current_user.id).all()
    return render_template(
        'areas.html',
        title='Gestionar Áreas',
        areas=lista_areas,
        form=form
    )

@app.route('/misiones', methods=['GET', 'POST'])
@login_required
def misiones():
    """Página para ver y crear Misiones (Metas y Proyectos)."""
    form = MisionForm()
    # Llenamos dinámicamente el <select> del formulario con las áreas del usuario
    form.area.choices = [(a.id, a.nombre) for a in AreaVida.query.filter_by(user_id=current_user.id).all()]
    
    if form.validate_on_submit():
        nueva_mision = Mision(
            titulo=form.titulo.data,
            recompensa_xp=form.recompensa_xp.data,
            recompensa_pesos=form.recompensa_pesos.data,
            area_id=form.area.data,
            autor=current_user
        )
        db.session.add(nueva_mision)
        db.session.commit()
        flash('¡Misión creada!', 'success')
        return redirect(url_for('misiones'))
        
    lista_misiones = Mision.query.filter_by(user_id=current_user.id).order_by(Mision.completada.asc()).all()
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
    # Llenamos dinámicamente el <select> del formulario
    form.area.choices = [(a.id, a.nombre) for a in AreaVida.query.filter_by(user_id=current_user.id).all()]

    if form.validate_on_submit():
        nuevo_habito = Habito(
            titulo=form.titulo.data,
            recompensa_xp=form.recompensa_xp.data,
            recompensa_pesos=form.recompensa_pesos.data,
            penalizacion_vida=form.penalizacion_vida.data,
            area_id=form.area.data,
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
    items_tienda = TiendaItem.query.all()
    
    return render_template(
        'tienda.html',
        title='Tienda',
        tienda=items_tienda,
        pesos_usuario=current_user.pesos
    )

@app.route('/perfil')
@login_required
def perfil():
    """Página de Perfil y Estadísticas detalladas."""
    stats = current_user
    xp_percent = (stats.xp_actual / stats.xp_siguiente_nivel) * 100
    
    return render_template(
        'perfil.html',
        title='Mi Perfil',
        stats=stats,
        xp_percent=xp_percent
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
        
    logros_publicos = LogroCompartido.query.order_by(LogroCompartido.timestamp.desc()).limit(20).all()
    
    return render_template(
        'feed.html',
        title='Feed de Logros',
        form=form,
        logros=logros_publicos
    )

# === Rutas de Acciones (Completar, Comprar, etc.) ===

@app.route('/completar_habito/<int:habito_id>', methods=['POST'])
@login_required
def completar_habito(habito_id):
    habito = Habito.query.get_or_404(habito_id)
    if habito.autor != current_user:
        return redirect(url_for('habitos')) # No es su hábito

    # Lógica del juego
    current_user.xp_actual += habito.recompensa_xp
    current_user.pesos += habito.recompensa_pesos
    habito.racha += 1
    current_user.ajustar_vida(1) # Curar 1 HP por éxito
    
    # Lógica de subir de nivel (simplificada)
    if current_user.xp_actual >= current_user.xp_siguiente_nivel:
        current_user.nivel += 1
        current_user.xp_actual -= current_user.xp_siguiente_nivel
        current_user.xp_siguiente_nivel = int(current_user.xp_siguiente_nivel * 1.5) # Dificultad incremental
        flash(f'¡Felicidades, subiste al Nivel {current_user.nivel}!', 'success')
        current_user.ajustar_vida(100) # Curar toda la vida al subir de nivel
        flash('¡Vida (HP) restaurada al máximo!', 'info')

    db.session.commit()
    flash(f'¡Hábito completado! Ganaste {habito.recompensa_pesos} COP.', 'info')
    return redirect(request.referrer or url_for('index')) # Volver a la página anterior

# NUEVA RUTA: Para fallar un hábito
@app.route('/fallar_habito/<int:habito_id>', methods=['POST'])
@login_required
def fallar_habito(habito_id):
    habito = Habito.query.get_or_404(habito_id)
    if habito.autor != current_user:
        return redirect(url_for('habitos'))

    # Lógica de penalización
    dano = habito.penalizacion_vida
    current_user.ajustar_vida(-dano)
    racha_perdida = habito.racha
    habito.racha = 0 # Reiniciar racha
    
    db.session.commit()
    
    flash(f'Fallaste el hábito. Racha de {racha_perdida} días perdida.', 'warning')
    flash(f'Perdiste {dano} HP.', 'danger')
    
    if current_user.vida == 0:
        flash('¡Tu vida ha llegado a 0! Has sido penalizado.', 'danger')
        # Aquí podrías añadir más penalizaciones (ej. perder pesos, XP)
        current_user.pesos = max(0, current_user.pesos - 10000)
        current_user.vida = 50 # Restaurar a 50% de vida
        db.session.commit()
        flash('Perdiste $ 10.000 COP. Tu vida se restauró al 50%.', 'danger')

    return redirect(request.referrer or url_for('index')) # Volver a la página anterior

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
            TiendaItem(nombre="1h de Videojuegos", costo_pesos=20000),
            TiendaItem(nombre="Cena especial (delivery)", costo_pesos=50000),
            TiendaItem(nombre="Día libre de tareas", costo_pesos=100000)
        ])
        db.session.commit()
    
    print("Base de datos inicializada y poblada con la tienda.")