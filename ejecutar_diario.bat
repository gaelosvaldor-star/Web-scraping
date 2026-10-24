@echo off
rem Extraccion diaria de precios (Cyberpuerta y Elektra). Se puede ejecutar con doble clic
rem o programar en el Programador de tareas de Windows.
cd /d "%~dp0"
if not exist data\raw mkdir data\raw
set PYTHONIOENCODING=utf-8
python scraping\extraer_precios.py >> data\raw\log_extraccion.txt 2>&1
