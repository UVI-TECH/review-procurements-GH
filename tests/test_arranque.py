"""Pruebas mínimas de la Fase 0: el proyecto arranca y la configuración base es la esperada."""

import os
import subprocess
import sys

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command

from config.entorno import BASE_DIR


def test_check_sin_errores():
    call_command("check", fail_level="WARNING")


@pytest.mark.django_db
def test_no_faltan_migraciones():
    call_command("makemigrations", check=True, dry_run=True, verbosity=0)


@pytest.mark.django_db
def test_admin_responde(client):
    respuesta = client.get("/admin/login/")
    assert respuesta.status_code == 200


def test_modelo_de_usuario_propio():
    assert get_user_model()._meta.label == "cuentas.Usuario"


def test_pruebas_fuerza_motor_simulado():
    assert settings.MOTOR_SIMULADO is True


def test_falta_secret_key_da_mensaje_claro():
    # Una variable vacía en el entorno gana sobre el .env, así la prueba no depende de él.
    entorno = {**os.environ, "DJANGO_SECRET_KEY": ""}
    resultado = subprocess.run(
        [sys.executable, "-c", "import config.settings.base"],
        cwd=BASE_DIR,
        env=entorno,
        capture_output=True,
        text=True,
    )
    assert resultado.returncode != 0
    assert "Define DJANGO_SECRET_KEY en el .env (ver .env.example)" in resultado.stderr
