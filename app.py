import os
import json
import textwrap
import google.generativeai as genai
from flask import Flask, render_template, url_for, redirect, flash, request, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, TextAreaField, SelectField, RadioField
from wtforms.validators import DataRequired, Email, EqualTo, Length, InputRequired
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import click

# --- Configuración de la App ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'una-clave-secreta-muy-dificil-de-adivinar')

# --- Configuración de la Base de Datos (Aiven) ---
AIVEN_DB_URI = os.environ.get('AIVEN_DATABASE_URI_PROGRESO')
if not AIVEN_DB_URI:
    AIVEN_DB_URI = 'sqlite:///progreso.db' # Fallback local
elif AIVEN_DB_URI.startswith("postgres://"):
    AIVEN_DB_URI = AIVEN_DB_URI.replace("postgres://", "postgresql+psycopg2://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = AIVEN_DB_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- Configuración de Flask-Login (Autenticación) ---
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Debes iniciar sesión para ver esta página.'
login_manager.login_message_category = 'info'

# --- Configuración de la API de Gemini ---
try:
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
    genai.configure(api_key=GEMINI_API_KEY)
except Exception as e:
    app.logger.error(f"Error configurando Gemini: {e}")

# --- Filtro Jinja para formato de moneda (COP) ---
@app.template_filter('format_pesos')
def format_pesos_filter(value):
    if value is None:
        return "$ 0"
    return f"$ {value:,.0f}".replace(",", ".") + " COP"

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
    pesos = db.Column(db.Integer, default=10000) # Moneda COP
    vida = db.Column(db.Integer, default=100) # Vida en %

    # Campos del Perfil (para la IA)
    edad = db.Column(db.String(50))
    tiempo_libre = db.Column(db.String(100))
    hobbies = db.Column(db.Text)
    metas_personales = db.Column(db.Text)
    metas_profesionales = db.Column(db.Text)

    # Relaciones
    areas = db.relationship('AreaVida', backref='autor', lazy=True, cascade="all, delete-orphan")
    misiones = db.relationship('Mision', backref='autor', lazy=True, cascade="all, delete-orphan")
    habitos = db.relationship('Habito', backref='autor', lazy=True, cascade="all, delete-orphan")
    logros_compartidos = db.relationship('LogroCompartido', backref='autor', lazy=True, cascade="all, delete-orphan")
    tienda_items = db.relationship('TiendaItem', backref='autor', lazy=True, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class AreaVida(db.Model):
    __tablename__ = 'area_vida'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    icono_svg = db.Column(db.String(100), nullable=False, default='icono-default')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
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
    area_id = db.Column(db.Integer, db.ForeignKey('area_vida.id'), nullable=True) # Ligada a un área
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
    penalizacion_vida = db.Column(db.Integer, default=5) # Penalización de HP
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    area_id = db.Column(db.Integer, db.ForeignKey('area_vida.id'), nullable=True) # Ligada a un área

class TiendaItem(db.Model):
    __tablename__ = 'tienda_item'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    costo_pesos = db.Column(db.Integer, nullable=False) # Costo en COP
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False) # Tienda personalizada

class LogroCompartido(db.Model):
    __tablename__ = 'logro_compartido'
    id = db.Column(db.Integer, primary_key=True)
    texto = db.Column(db.String(500), nullable=False)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# === Formularios (Flask-WTF) ===

class RegistrationStep1Form(FlaskForm):
    username = StringField('Usuario', validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField('Contraseña', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirmar Contraseña', validators=[DataRequired(), EqualTo('password', message='Las contraseñas deben coincidir.')])
    submit = SubmitField('Siguiente Paso')

class RegistrationStep2Form(FlaskForm):
    edad = SelectField('¿Cuál es tu rango de edad?', choices=[
        ('18-25', '18-25 años'),
        ('26-35', '26-35 años'),
        ('36-45', '36-45 años'),
        ('46+', '46+ años')
    ], validators=[DataRequired()])
    tiempo_libre = RadioField('¿Cuánto tiempo libre tienes al día?', choices=[
        ('Poco', 'Poco (< 1 hora)'),
        ('Moderado', 'Moderado (1-2 horas)'),
        ('Mucho', 'Mucho (> 2 horas)')
    ], validators=[DataRequired()])
    hobbies = TextAreaField('¿Cuáles son tus hobbies e intereses?', validators=[DataRequired(), Length(min=10, max=500)], render_kw={"placeholder": "Ej. Jugar videojuegos, leer ciencia ficción, hacer senderismo, cocinar..."})
    submit = SubmitField('Siguiente Paso')

class RegistrationStep3Form(FlaskForm):
    metas_personales = TextAreaField('Describe tus metas personales. ¿Qué quieres mejorar?', validators=[DataRequired(), Length(min=10, max=1000)], render_kw={"placeholder": "Ej. Quiero ser más organizado, comer más saludable, aprender a tocar guitarra, mejorar mi relación con mi familia..."})
    metas_profesionales = TextAreaField('Describe tus metas profesionales o de estudio.', validators=[DataRequired(), Length(min=10, max=1000)], render_kw={"placeholder": "Ej. Conseguir un ascenso, aprender a programar en Python, terminar mi tesis, encontrar un nuevo trabajo, ser más productivo..."})
    submit = SubmitField('¡Generar mi ProgreSO con IA!')

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Contraseña', validators=[DataRequired()])
    submit = SubmitField('Iniciar Sesión')

class AreaVidaForm(FlaskForm):
    nombre = StringField('Nombre del Área', validators=[DataRequired(), Length(max=100)])
    icono_svg = SelectField('Elige un Icono', choices=[
        ('icono-salud', 'Salud (Corazón)'),
        ('icono-dinero', 'Finanzas (Dinero)'),
        ('icono-carrera', 'Carrera (Maletín)'),
        ('icono-estudio', 'Estudio (Libro)'),
        ('icono-mente', 'Mente (Cerebro)'),
        ('icono-social', 'Social (Personas)'),
        ('icono-hobby', 'Hobby (Guitarra)'),
        ('icono-default', 'General (Estrella)')
    ], validators=[DataRequired()])
    submit = SubmitField('Crear Área')

class MisionForm(FlaskForm):
    area_id = SelectField('Área de Vida', coerce=int, validators=[InputRequired()])
    titulo = StringField('Título de la Misión', validators=[DataRequired(), Length(max=200)])
    recompensa_xp = StringField('Recompensa XP', default=50, validators=[DataRequired()])
    recompensa_pesos = StringField('Recompensa (COP)', default=5000, validators=[DataRequired()])
    submit = SubmitField('Crear Misión')

class HabitoForm(FlaskForm):
    area_id = SelectField('Área de Vida', coerce=int, validators=[InputRequired()])
    titulo = StringField('Título del Hábito', validators=[DataRequired(), Length(max=200)])
    recompensa_xp = StringField('Recompensa XP', default=10, validators=[DataRequired()])
    recompensa_pesos = StringField('Recompensa (COP)', default=1000, validators=[DataRequired()])
    penalizacion_vida = StringField('Penalización (HP)', default=5, validators=[DataRequired()])
    submit = SubmitField('Crear Hábito')

class ShareLogroForm(FlaskForm):
    texto = TextAreaField('Comparte tu logro...', validators=[DataRequired(), Length(min=1, max=500)], render_kw={"placeholder": "Ej. ¡Subí a Nivel 5!"})
    submit = SubmitField('Publicar')


# === Rutas de Autenticación y Registro con IA ===

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
            # Si el usuario no ha completado el registro, lo enviamos al paso 2
            if not user.edad:
                return redirect(url_for('register_step_2'))
            return redirect(url_for('index'))
        else:
            flash('Login fallido. Revisa tu email y contraseña.', 'danger')
    return render_template('login.html', title='Iniciar Sesión', form=form)

@app.route('/register/step1', methods=['GET', 'POST'])
def register_step_1():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegistrationStep1Form()
    if form.validate_on_submit():
        # Validar si el email o username ya existen
        existing_email = User.query.filter_by(email=form.email.data).first()
        if existing_email:
            flash('Ese email ya está registrado. Por favor, inicia sesión.', 'warning')
            return redirect(url_for('login'))
        existing_username = User.query.filter_by(username=form.username.data).first()
        if existing_username:
            flash('Ese nombre de usuario ya existe. Por favor, elige otro.', 'danger')
            return render_template('register_step_1.html', title='Registro - Paso 1', form=form)

        hashed_password = generate_password_hash(form.password.data)
        user = User(username=form.username.data, email=form.email.data, password_hash=hashed_password)
        db.session.add(user)
        try:
            db.session.commit()
            login_user(user) # Logueamos al usuario
            flash('¡Cuenta creada! Ahora cuéntanos un poco sobre ti.', 'success')
            return redirect(url_for('register_step_2'))
        except Exception as e:
            db.session.rollback()
            flash('Error al registrar. Inténtalo de nuevo.', 'danger')
            app.logger.error(f"Error en registro (Paso 1): {e}")
            
    return render_template('register_step_1.html', title='Registro - Paso 1', form=form)

@app.route('/register/step2', methods=['GET', 'POST'])
@login_required
def register_step_2():
    if current_user.edad: # Si ya completó este paso, saltar al 3
        return redirect(url_for('register_step_3'))
    form = RegistrationStep2Form()
    if form.validate_on_submit():
        current_user.edad = form.edad.data
        current_user.tiempo_libre = form.tiempo_libre.data
        current_user.hobbies = form.hobbies.data
        try:
            db.session.commit()
            flash('¡Perfil guardado! Ahora, tus metas.', 'success')
            return redirect(url_for('register_step_3'))
        except Exception as e:
            db.session.rollback()
            flash('Error al guardar tu perfil. Inténtalo de nuevo.', 'danger')
            app.logger.error(f"Error en registro (Paso 2): {e}")
            
    return render_template('register_step_2.html', title='Registro - Paso 2', form=form)

@app.route('/register/step3', methods=['GET', 'POST'])
@login_required
def register_step_3():
    if not current_user.edad: # Forzar a ir al paso 2 si no lo ha completado
        return redirect(url_for('register_step_2'))
    if current_user.areas: # Si ya tiene áreas, es que la IA ya corrió
        return redirect(url_for('index'))
        
    form = RegistrationStep3Form()
    if form.validate_on_submit():
        current_user.metas_personales = form.metas_personales.data
        current_user.metas_profesionales = form.metas_profesionales.data
        try:
            db.session.commit()
            # ¡Aquí llamamos a la IA!
            # Esto se hace en una ruta separada para manejar el 'loading'
            return redirect(url_for('generar_setup_ia'))
        except Exception as e:
            db.session.rollback()
            flash('Error al guardar tus metas. Inténtalo de nuevo.', 'danger')
            app.logger.error(f"Error en registro (Paso 3): {e}")
            
    return render_template('register_step_3.html', title='Registro - Paso 3', form=form)

@app.route('/generar_setup_ia', methods=['GET'])
@login_required
def generar_setup_ia():
    """
    Esta es la ruta que se llama DESPUÉS del paso 3.
    Maneja la llamada a la API de Gemini y puebla la base de datos.
    """
    try:
        if not current_user.metas_profesionales:
             flash('Debes completar el registro primero.', 'danger')
             return redirect(url_for('register_step_3'))
        
        if current_user.areas: # Evitar que corra dos veces
            flash('Tu ProgreSO ya ha sido generado.', 'info')
            return redirect(url_for('index'))

        app.logger.info(f"Iniciando generación de IA para usuario: {current_user.email}")
        ai_response = generate_ai_setup(current_user)
        
        if not ai_response:
             flash('Hubo un error con la IA. Se usarán valores por defecto.', 'danger')
             # (Aquí podríamos llamar a una función de setup por defecto)
             return redirect(url_for('index'))

        # Procesar la respuesta JSON de la IA
        data = json.loads(ai_response)
        
        # 1. Crear Áreas de Vida
        areas_map = {} # Para mapear nombres de IA a IDs de BD
        for area in data.get('areas_vida', []):
            nueva_area = AreaVida(
                nombre=area.get('nombre'),
                icono_svg=area.get('icono_svg', 'icono-default'),
                autor=current_user
            )
            db.session.add(nueva_area)
            db.session.flush() # Para obtener el ID antes del commit
            areas_map[area.get('nombre')] = nueva_area.id

        # 2. Crear Hábitos
        for habito in data.get('habitos', []):
            area_id = areas_map.get(habito.get('area_nombre')) # Buscar el ID del área
            nuevo_habito = Habito(
                titulo=habito.get('titulo'),
                recompensa_xp=habito.get('recompensa_xp', 10),
                recompensa_pesos=habito.get('recompensa_pesos', 1000),
                penalizacion_vida=habito.get('penalizacion_vida', 5),
                autor=current_user,
                area_id=area_id
            )
            db.session.add(nuevo_habito)

        # 3. Crear Misiones
        for mision in data.get('misiones', []):
            area_id = areas_map.get(mision.get('area_nombre'))
            nueva_mision = Mision(
                titulo=mision.get('titulo'),
                recompensa_xp=mision.get('recompensa_xp', 50),
                recompensa_pesos=mision.get('recompensa_pesos', 5000),
                autor=current_user,
                area_id=area_id
            )
            db.session.add(nueva_mision)
            db.session.flush() # Obtener el ID de la misión
            
            # 4. Crear Pendientes (Sub-tareas) para la Misión
            for pendiente_desc in mision.get('pendientes', []):
                nuevo_pendiente = Pendiente(
                    descripcion=pendiente_desc,
                    mision_id=nueva_mision.id
                )
                db.session.add(nuevo_pendiente)

        # 5. Crear Items de Tienda Personalizados
        for item in data.get('recompensas_tienda', []):
            nuevo_item = TiendaItem(
                nombre=item.get('nombre'),
                costo_pesos=item.get('costo_pesos', 10000),
                autor=current_user
            )
            db.session.add(nuevo_item)
            
        db.session.commit()
        app.logger.info(f"Generación de IA completada para: {current_user.email}")
        flash('¡Tu plan de vida personalizado ha sido generado por la IA!', 'success')
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error fatal en 'generar_setup_ia' para {current_user.email}: {e}")
        flash('Hubo un error procesando la respuesta de la IA. Por favor, contacta a soporte.', 'danger')
        
    return redirect(url_for('index'))


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
    # Si el usuario no ha completado el registro, lo forzamos
    if not current_user.edad:
        return redirect(url_for('register_step_2'))
    if not current_user.metas_personales:
        return redirect(url_for('register_step_3'))
    if not current_user.areas: # Si no tiene áreas, la IA no ha corrido
        return redirect(url_for('generar_setup_ia'))

    stats = current_user
    xp_percent = (stats.xp_actual / stats.xp_siguiente_nivel) * 100
    
    # Obtenemos las áreas con sus misiones y hábitos precargados
    areas = AreaVida.query.filter_by(user_id=stats.id).all()
    
    return render_template(
        'index.html',
        title='Panel Central',
        stats=stats,
        xp_percent=xp_percent,
        areas=areas
    )

@app.route('/areas', methods=['GET', 'POST'])
@login_required
def areas():
    """Página para gestionar las Áreas de Vida."""
    form = AreaVidaForm()
    if form.validate_on_submit():
        nueva_area = AreaVida(
            nombre=form.nombre.data,
            icono_svg=form.icono_svg.data,
            autor=current_user
        )
        db.session.add(nueva_area)
        db.session.commit()
        flash('¡Área creada con éxito!', 'success')
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
    # Llenamos dinámicamente las opciones del SelectField
    form.area_id.choices = [(a.id, a.nombre) for a in AreaVida.query.filter_by(user_id=current_user.id).all()]
    
    if form.validate_on_submit():
        nueva_mision = Mision(
            titulo=form.titulo.data,
            area_id=form.area_id.data,
            recompensa_xp=int(form.recompensa_xp.data),
            recompensa_pesos=int(form.recompensa_pesos.data),
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
    # Llenamos dinámicamente las opciones del SelectField
    form.area_id.choices = [(a.id, a.nombre) for a in AreaVida.query.filter_by(user_id=current_user.id).all()]
    
    if form.validate_on_submit():
        nuevo_habito = Habito(
            titulo=form.titulo.data,
            area_id=form.area_id.data,
            recompensa_xp=int(form.recompensa_xp.data),
            recompensa_pesos=int(form.recompensa_pesos.data),
            penalizacion_vida=int(form.penalizacion_vida.data),
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
    """Página de La Tienda (Recompensas Personalizadas)."""
    if request.method == 'POST':
        item_id = request.form.get('item_id')
        item = TiendaItem.query.get_or_404(item_id)
        
        if item.autor != current_user:
             flash('Acción no permitida.', 'danger')
             return redirect(url_for('tienda'))

        if current_user.pesos >= item.costo_pesos:
            current_user.pesos -= item.costo_pesos
            # (Aquí podríamos añadir lógica para "activar" la recompensa)
            db.session.commit()
            flash(f'¡Has comprado "{item.nombre}"!', 'success')
        else:
            flash('No tienes suficientes pesos (COP).', 'danger')
        return redirect(url_for('tienda'))

    items_tienda = TiendaItem.query.filter_by(user_id=current_user.id).all()
    
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
        
    logros_publicos = LogroCompartido.query.order_by(LogroCompartido.timestamp.desc()).limit(20).all()
    
    return render_template(
        'feed.html',
        title='Feed de Logros',
        form=form,
        logros=logros_publicos
    )

# === Rutas de Acciones (Completar, Fallar, etc.) ===

@app.route('/completar_habito/<int:habito_id>', methods=['POST'])
@login_required
def completar_habito(habito_id):
    habito = Habito.query.get_or_404(habito_id)
    if habito.autor != current_user:
        return redirect(url_for('habitos'))

    # Lógica del juego
    current_user.xp_actual += habito.recompensa_xp
    current_user.pesos += habito.recompensa_pesos
    habito.racha += 1
    
    # Curar 1 HP al completar, sin pasar de 100
    current_user.vida = min(current_user.vida + 1, 100)
    
    # Lógica de subir de nivel
    if current_user.xp_actual >= current_user.xp_siguiente_nivel:
        current_user.nivel += 1
        current_user.xp_actual -= current_user.xp_siguiente_nivel
        current_user.xp_siguiente_nivel = int(current_user.xp_siguiente_nivel * 1.5)
        flash(f'¡Felicidades, subiste al Nivel {current_user.nivel}!', 'success')

    db.session.commit()
    flash(f'¡Hábito "{habito.titulo}" completado! (+{habito.recompensa_xp} XP, +{habito.recompensa_pesos} COP)', 'info')
    return redirect(request.referrer or url_for('habitos'))

@app.route('/fallar_habito/<int:habito_id>', methods=['POST'])
@login_required
def fallar_habito(habito_id):
    habito = Habito.query.get_or_404(habito_id)
    if habito.autor != current_user:
        return redirect(url_for('habitos'))
        
    # Penalización de vida, sin bajar de 0
    current_user.vida = max(current_user.vida - habito.penalizacion_vida, 0)
    
    # Romper la racha
    racha_rota = habito.racha
    habito.racha = 0
    
    db.session.commit()
    
    if racha_rota > 0:
        flash(f'Racha de "{habito.titulo}" rota. ¡Ánimo! (-{habito.penalizacion_vida} HP)', 'warning')
    else:
        flash(f'Hábito fallado. (-{habito.penalizacion_vida} HP)', 'warning')
        
    return redirect(request.referrer or url_for('habitos'))


# === Función de IA de Gemini ===

def generate_ai_setup(user):
    """
    Llama a la API de Gemini para generar un plan de vida personalizado
    basado en las respuestas de registro del usuario.
    """
    if not GEMINI_API_KEY:
        app.logger.error("GEMINI_API_KEY no está configurada. No se puede generar plan de IA.")
        return None

    try:
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash", # Usamos el modelo Flash
            generation_config={"response_mime_type": "application/json"} # Pedimos JSON
        )

        # Prompt detallado para la IA
        prompt = textwrap.dedent(f"""
        Eres "ProgreSO", un coach de vida experto en gamificación. Un nuevo usuario se ha registrado y 
        necesita un plan de inicio personalizado. Tu misión es generar un JSON ESTRUCTURADO basado en 
        su perfil.

        **Moneda Local:** Pesos Colombianos (COP). Usa valores razonables, ej. un café (5000 COP), una cena (50000 COP).

        **Perfil del Usuario:**
        - **Edad:** {user.edad}
        - **Tiempo Libre:** {user.tiempo_libre}
        - **Hobbies:** {user.hobbies}
        - **Metas Personales:** {user.metas_personales}
        - **Metas Profesionales/Estudio:** {user.metas_profesionales}

        **Tu Tarea:**
        Genera un plan de inicio con 4 componentes: "areas_vida", "habitos", "misiones", y "recompensas_tienda".

        **REGLAS ESTRICTAS DEL JSON DE SALIDA:**

        1.  **areas_vida:** Crea 3 o 4 áreas de vida CLAVE basadas en sus metas.
            - "nombre": El nombre del área (ej. "Salud Física", "Carrera Tech", "Finanzas Personales").
            - "icono_svg": Asigna un icono de esta lista: ['icono-salud', 'icono-dinero', 'icono-carrera', 'icono-estudio', 'icono-mente', 'icono-social', 'icono-hobby', 'icono-default'].

        2.  **habitos:** Crea 3 hábitos diarios o recurrentes.
            - "titulo": El hábito (ej. "Meditar 10 minutos", "Estudiar Python 30 min").
            - "area_nombre": El "nombre" EXACTO de una de las 'areas_vida' que creaste.
            - "recompensa_xp": Número (ej. 10).
            - "recompensa_pesos": Número (ej. 1000).
            - "penalizacion_vida": Número (ej. 5).

        3.  **misiones:** Crea 2 misiones (metas a corto/medio plazo).
            - "titulo": La misión (ej. "Completar curso de Flask", "Crear un fondo de emergencia").
            - "area_nombre": El "nombre" EXACTO de una de las 'areas_vida' que creaste.
            - "recompensa_xp": Número (ej. 100).
            - "recompensa_pesos": Número (ej. 10000).
            - "pendientes": Un array de strings [ "Sub-tarea 1", "Sub-tarea 2" ].

        4.  **recompensas_tienda:** Crea 3 recompensas personalizadas basadas en sus HOBBIES.
            - "nombre": La recompensa (ej. "Comprar un libro nuevo", "1 hora de videojuegos", "Pedir cena").
            - "costo_pesos": Número (ej. 25000).

        **Ejemplo de formato JSON de salida (¡SÍGUELO!):**
        {{
            "areas_vida": [
                {{"nombre": "Salud y Bienestar", "icono_svg": "icono-salud"}},
                {{"nombre": "Desarrollo Profesional", "icono_svg": "icono-carrera"}}
            ],
            "habitos": [
                {{"titulo": "Hacer 30 min de ejercicio", "area_nombre": "Salud y Bienestar", "recompensa_xp": 10, "recompensa_pesos": 1500, "penalizacion_vida": 5}},
                {{"titulo": "Estudiar 1 módulo de AWS", "area_nombre": "Desarrollo Profesional", "recompensa_xp": 15, "recompensa_pesos": 2000, "penalizacion_vida": 5}}
            ],
            "misiones": [
                {{"titulo": "Correr una 5K", "area_nombre": "Salud y Bienestar", "recompensa_xp": 200, "recompensa_pesos": 20000, "pendientes": ["Entrenar 3 veces por semana", "Comprar zapatillas de running", "Inscribirse a la carrera"]}}
            ],
            "recompensas_tienda": [
                {{"nombre": "Comprar un nuevo videojuego", "costo_pesos": 150000}},
                {{"nombre": "Noche de pizza y película", "costo_pesos": 60000}}
            ]
        }}
        """)
        
        app.logger.info("Enviando prompt a Gemini...")
        response = model.generate_content(prompt)
        app.logger.info("Respuesta de Gemini recibida.")
        
        # Limpiar la respuesta para asegurar que es JSON válido
        cleaned_response = response.text.strip().replace("```json", "").replace("```", "")
        
        return cleaned_response

    except Exception as e:
        app.logger.error(f"Error en generate_ai_setup: {e}")
        return None

# === Comandos CLI para la App ===

@app.cli.command("init-db")
def init_db_command():
    """Limpia la BD existente y crea nuevas tablas."""
    
    # En producción (Render), queremos que esto solo cree las tablas si no existen.
    # En desarrollo, podríamos descomentar db.drop_all() para limpiar.
    # db.drop_all() 
    
    db.create_all()
    print("Base de datos inicializada (tablas creadas si no existían).")
    # Ya no poblamos la tienda aquí, se hace con la IA en el registro.