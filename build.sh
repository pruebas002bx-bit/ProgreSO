#!/usr/bin/env bash
# Exit on error
set -o errexit

# 1. Instalar las dependencias de Python
pip install -r requirements.txt

# 2. Ejecutar nuestro comando 'init-db' (definido en app.py)
# Esto creará las tablas en la base de datos de Aiven
flask init-db