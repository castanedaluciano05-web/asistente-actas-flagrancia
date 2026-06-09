import streamlit as st
import streamlit.components.v1 as components
import json
import os
import re
import math
from pathlib import Path
from datetime import date
from textwrap import dedent
from io import BytesIO

import pandas as pd
from PIL import Image, ImageOps

try:
    import google.generativeai as genai
except Exception:
    genai = None

# =====================================================
# CONFIGURACIÓN GENERAL
# =====================================================

st.set_page_config(
    page_title="CastaMuebles IA V10 - Tablas ajustadas",
    page_icon="🧵",
    layout="wide"
)

ARCHIVO_BACKUP = Path("backup_castamuebles_pro.json")

DOBLADILLO_LATERAL_CM = 4
DOBLADILLO_TOTAL_M = 0.08
SOLAPA_DEFAULT_CM = 10
CABEZAL_DEFAULT_CM = 16
RUEDO_DEFAULT_CM = 5
SEPARACION_TABLAS_CM = 10
# Valor objetivo de tabla. Si la medida visible no es múltiplo de 10,
# la tabla real se ajusta lo más cerca posible a 10 cm para empezar y terminar en tabla.
# Taller actual: cabezal/superior 16 cm + ruedo/inferior 5 cm = altura de corte +21 cm por defecto.

APERTURAS = ["Central", "Derecha", "Izquierda", "Lateral"]
TIPOS_TRABAJO = ["Vertical", "Apaisado"]
PANOS_SOLAPA = ["Izquierda", "Derecha"]


# =====================================================
# ESTILO GENERAL STREAMLIT
# =====================================================

st.markdown("""
<style>
.main-title {
    font-size: 34px;
    font-weight: 800;
    color: #1f2937;
    margin-bottom: 0px;
}
.subtitle {
    font-size: 16px;
    color: #6b7280;
    margin-bottom: 25px;
}
.important-box {
    padding: 16px;
    border-radius: 12px;
    background-color: #fff7ed;
    border: 1px solid #fed7aa;
    color: #7c2d12;
    font-weight: 600;
    margin-top: 10px;
    margin-bottom: 15px;
}
.ok-box {
    padding: 16px;
    border-radius: 12px;
    background-color: #ecfdf5;
    border: 1px solid #a7f3d0;
    color: #065f46;
    font-weight: 600;
    margin-bottom: 15px;
}
.danger-box {
    padding: 16px;
    border-radius: 12px;
    background-color: #fef2f2;
    border: 1px solid #fecaca;
    color: #991b1b;
    font-weight: 700;
    margin-bottom: 15px;
}
.info-box {
    padding: 16px;
    border-radius: 12px;
    background-color: #eff6ff;
    border: 1px solid #bfdbfe;
    color: #1e3a8a;
    font-weight: 600;
    margin-bottom: 15px;
}

.cortina-header-card {
    background: linear-gradient(135deg, #fff7ed 0%, #ffedd5 100%);
    border: 2px solid #fb923c;
    border-radius: 18px;
    padding: 16px 18px;
    margin: 10px 0 8px 0;
    box-shadow: 0 6px 18px rgba(194, 65, 12, 0.12);
}
.cortina-header-title {
    font-size: 25px;
    font-weight: 950;
    color: #7c2d12;
    line-height: 1.2;
}
.cortina-header-subtitle {
    font-size: 15px;
    font-weight: 800;
    color: #9a3412;
    margin-top: 4px;
}
div.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #f97316 0%, #dc2626 100%);
    color: white;
    border: 2px solid #9a3412;
    border-radius: 16px;
    min-height: 58px;
    font-size: 18px;
    font-weight: 950;
    box-shadow: 0 8px 18px rgba(220, 38, 38, 0.22);
}
div.stButton > button[kind="primary"]:hover {
    border: 2px solid #7f1d1d;
    filter: brightness(0.98);
}
</style>
""", unsafe_allow_html=True)


# =====================================================
# ESTADO Y BACKUP
# =====================================================

def estado_inicial():
    return {
        "cliente": "",
        "telefono": "",
        "fecha": str(date.today()),
        "observaciones": "",
        "telas": []
    }


def guardar_backup():
    with open(ARCHIVO_BACKUP, "w", encoding="utf-8") as f:
        json.dump(st.session_state.data, f, ensure_ascii=False, indent=4)


def cargar_backup():
    if "data" not in st.session_state:
        if ARCHIVO_BACKUP.exists():
            try:
                with open(ARCHIVO_BACKUP, "r", encoding="utf-8") as f:
                    st.session_state.data = json.load(f)
            except Exception:
                st.session_state.data = estado_inicial()
        else:
            st.session_state.data = estado_inicial()


def resetear_todo():
    if ARCHIVO_BACKUP.exists():
        ARCHIVO_BACKUP.unlink()
    st.session_state.data = estado_inicial()
    st.rerun()


def normalizar_cortina(cortina):
    cortina.setdefault("ambiente", "Cortina")
    cortina.setdefault("tipo_trabajo", "Vertical")
    cortina.setdefault("apertura", "Central")
    cortina.setdefault("ancho_riel", 2.40)
    cortina.setdefault("alto_terminado", 2.51)
    cortina.setdefault("cabezal_cm", CABEZAL_DEFAULT_CM)
    cortina.setdefault("ruedo_cm", RUEDO_DEFAULT_CM)
    cortina.setdefault("metraje_asignado", 0.0)

    if cortina["apertura"] == "Central":
        cortina.setdefault("ancho_pano_izq", round(float(cortina["ancho_riel"]) / 2, 2))
        cortina.setdefault("ancho_pano_der", round(float(cortina["ancho_riel"]) / 2, 2))
        cortina.setdefault("hay_cruce", True)
        cortina.setdefault("pano_solapa", "Derecha")
    else:
        cortina.setdefault("ancho_pano_izq", 0.0)
        cortina.setdefault("ancho_pano_der", 0.0)
        cortina.setdefault("hay_cruce", False)
        cortina.setdefault("pano_solapa", "Derecha")

    return cortina


cargar_backup()

if "ordenes_detectadas" not in st.session_state:
    st.session_state.ordenes_detectadas = []


# =====================================================
# REGLAS TEXTILES
# =====================================================

def hay_solapa_real(apertura, hay_cruce):
    return apertura == "Central" and bool(hay_cruce)


def tablas_y_picos(medida_visible_m):
    """
    Calcula tablas y picos para que el paño empiece y termine en tabla.

    Regla aprobada por taller:
    - La tabla objetivo es 10 cm.
    - Si la medida visible no es múltiplo exacto de 10, se usa techo(medida_visible_cm / 10).
    - Luego la tabla real se ajusta apenas por debajo/cerca de 10 cm.
    - Picos = tablas - 1.

    Ejemplo: 205 cm visibles -> 21 tablas de 9.76 cm y 20 picos.
    """
    medida_visible_cm = max(float(medida_visible_m) * 100, 0.0)

    if medida_visible_cm <= 0:
        tablas = 2
    else:
        tablas = math.ceil((medida_visible_cm - 1e-9) / SEPARACION_TABLAS_CM)

    if tablas < 2:
        tablas = 2

    picos = tablas - 1
    return tablas, picos


def ancho_tabla_real_cm(medida_visible_m, tablas=None):
    """Ancho real de cada tabla para cerrar exacto sobre la medida visible."""
    if tablas is None:
        tablas, _ = tablas_y_picos(medida_visible_m)
    if tablas <= 0:
        return 0.0
    return (float(medida_visible_m) * 100) / tablas


def estructura_panos_cortina(cortina, solapa_cm):
    """
    Fórmula nueva, sin tocar estructura visual:
    arma la estructura rígida de cada paño del lote.

    Estructura rígida = ancho visible del paño + dobladillos.
    La solapa se suma solamente si hay cruce real entre paños.
    Los picos se cuentan por paño.
    """
    normalizar_cortina(cortina)

    apertura = cortina.get("apertura", "Central")
    ancho_riel = float(cortina.get("ancho_riel", 0.0))
    hay_cruce = bool(cortina.get("hay_cruce", apertura == "Central"))
    solapa_m = solapa_cm / 100 if hay_solapa_real(apertura, hay_cruce) else 0

    panos = []

    if apertura == "Central":
        ancho_izq = float(cortina.get("ancho_pano_izq", ancho_riel / 2))
        ancho_der = float(cortina.get("ancho_pano_der", ancho_riel / 2))
        pano_solapa = cortina.get("pano_solapa", "Derecha")

        visible_izq = ancho_izq
        visible_der = ancho_der

        if solapa_m > 0:
            if pano_solapa == "Izquierda":
                visible_izq += solapa_m
            else:
                visible_der += solapa_m

        tablas_izq, picos_izq = tablas_y_picos(visible_izq)
        tablas_der, picos_der = tablas_y_picos(visible_der)

        panos.append({
            "lado": "Izquierda",
            "visible": visible_izq,
            "trabajo": visible_izq + DOBLADILLO_TOTAL_M,
            "tablas": tablas_izq,
            "picos": picos_izq,
            "tabla_real_cm": ancho_tabla_real_cm(visible_izq, tablas_izq)
        })

        panos.append({
            "lado": "Derecha",
            "visible": visible_der,
            "trabajo": visible_der + DOBLADILLO_TOTAL_M,
            "tablas": tablas_der,
            "picos": picos_der,
            "tabla_real_cm": ancho_tabla_real_cm(visible_der, tablas_der)
        })

    else:
        visible = ancho_riel
        tablas, picos = tablas_y_picos(visible)

        panos.append({
            "lado": apertura,
            "visible": visible,
            "trabajo": visible + DOBLADILLO_TOTAL_M,
            "tablas": tablas,
            "picos": picos,
            "tabla_real_cm": ancho_tabla_real_cm(visible, tablas)
        })

    return panos


def calcular_pico_maestro_lote(tela):
    """
    Fórmula jerárquica del lote:

    Pico maestro = (metros recibidos - estructura rígida total) / picos totales.

    Se calcula una sola vez por tela/lote y se aplica a todas las cortinas
    de ese lote para que el dibujo del cabezal sea parejo.
    """
    metros_recibidos = float(tela.get("metros_recibidos", 0.0))
    solapa_cm = float(tela.get("solapa_cm", SOLAPA_DEFAULT_CM))

    estructura_total = 0.0
    picos_totales = 0

    for cortina in tela.get("cortinas", []):
        for pano in estructura_panos_cortina(cortina, solapa_cm):
            estructura_total += float(pano["trabajo"])
            picos_totales += int(pano["picos"])

    if picos_totales <= 0 or metros_recibidos <= 0:
        pico_maestro_cm = None
        excedente_m = 0.0
    else:
        excedente_m = metros_recibidos - estructura_total
        pico_maestro_cm = (excedente_m * 100) / picos_totales

    return {
        "metros_recibidos": metros_recibidos,
        "estructura_total": estructura_total,
        "picos_totales": picos_totales,
        "excedente_m": excedente_m,
        "pico_maestro_cm": pico_maestro_cm
    }


def base_consumo_cortina(cortina, solapa_cm):
    """
    Base rígida real de una cortina.

    Antes se calculaba como ancho_riel + solapa + 0.08 m.
    Eso era correcto para un solo paño, pero en apertura Central hay dos paños
    y cada paño lleva sus dobladillos laterales. Por seguridad, ahora se toma
    la misma estructura que usa el pico maestro: suma del trabajo de cada paño.
    """
    return sum(float(pano["trabajo"]) for pano in estructura_panos_cortina(cortina, solapa_cm))


def calcular_metraje_cortina(cortina, solapa_cm, fruncido):
    return base_consumo_cortina(cortina, solapa_cm) * fruncido


def total_base_tela(tela):
    total = 0
    for c in tela["cortinas"]:
        normalizar_cortina(c)
        total += base_consumo_cortina(c, tela["solapa_cm"])
    return total


def total_metraje_tela(tela, fruncido):
    total = 0
    for c in tela["cortinas"]:
        normalizar_cortina(c)
        total += calcular_metraje_cortina(c, tela["solapa_cm"], fruncido)
    return total


def fruncido_maximo_parejo(tela):
    base = total_base_tela(tela)
    if base <= 0:
        return 0
    return float(tela.get("metros_recibidos", 0.0)) / base


# =====================================================
# CÁLCULO DE CORTE
# =====================================================

def calcular_central(cortina, solapa_cm, metraje_asignado, pico_maestro_cm=None):
    ancho_riel = float(cortina["ancho_riel"])
    ancho_izq = float(cortina.get("ancho_pano_izq", ancho_riel / 2))
    ancho_der = float(cortina.get("ancho_pano_der", ancho_riel / 2))
    hay_cruce = bool(cortina.get("hay_cruce", True))
    pano_solapa = cortina.get("pano_solapa", "Derecha")

    solapa_m = solapa_cm / 100 if hay_solapa_real("Central", hay_cruce) else 0

    visible_izq = ancho_izq
    visible_der = ancho_der

    if solapa_m > 0:
        if pano_solapa == "Izquierda":
            visible_izq += solapa_m
        else:
            visible_der += solapa_m

    trabajo_izq = visible_izq + DOBLADILLO_TOTAL_M
    trabajo_der = visible_der + DOBLADILLO_TOTAL_M
    base_total = trabajo_izq + trabajo_der

    tablas_izq, picos_izq = tablas_y_picos(visible_izq)
    tablas_der, picos_der = tablas_y_picos(visible_der)
    tabla_real_izq_cm = ancho_tabla_real_cm(visible_izq, tablas_izq)
    tabla_real_der_cm = ancho_tabla_real_cm(visible_der, tablas_der)

    if pico_maestro_cm is not None:
        pico_izq = pico_maestro_cm
        pico_der = pico_maestro_cm
        corte_izq = trabajo_izq + ((pico_maestro_cm * picos_izq) / 100)
        corte_der = trabajo_der + ((pico_maestro_cm * picos_der) / 100)
        total_corte_calculado = corte_izq + corte_der
        fruncido_real = total_corte_calculado / base_total if base_total > 0 else 0
    else:
        # Regla aprobada: en cortina central se usa un único pico común
        # para ambos paños. El metraje total se reparte según la cantidad
        # de picos de cada paño, no por fruncido proporcional separado.
        total_picos = picos_izq + picos_der
        if base_total <= 0 or total_picos <= 0:
            fruncido_real = 0
            corte_izq = 0
            corte_der = 0
            pico_izq = 0
            pico_der = 0
        else:
            excedente_total_m = metraje_asignado - base_total
            pico_comun_cm = (excedente_total_m * 100) / total_picos
            pico_izq = pico_comun_cm
            pico_der = pico_comun_cm
            corte_izq = trabajo_izq + ((pico_comun_cm * picos_izq) / 100)
            corte_der = trabajo_der + ((pico_comun_cm * picos_der) / 100)
            fruncido_real = (corte_izq + corte_der) / base_total if base_total > 0 else 0

    return {
        "tipo": "Central",
        "ancho_riel": ancho_riel,
        "ancho_izq_sobre_riel": ancho_izq,
        "ancho_der_sobre_riel": ancho_der,
        "hay_cruce": hay_cruce,
        "pano_solapa": pano_solapa,
        "solapa_cm": solapa_cm if solapa_m > 0 else 0,
        "visible_izq": visible_izq,
        "visible_der": visible_der,
        "trabajo_izq": trabajo_izq,
        "trabajo_der": trabajo_der,
        "corte_izq": corte_izq,
        "corte_der": corte_der,
        "total_corte": corte_izq + corte_der,
        "fruncido_real": fruncido_real,
        "tablas_izq": tablas_izq,
        "tablas_der": tablas_der,
        "picos_izq": picos_izq,
        "picos_der": picos_der,
        "total_tablas": tablas_izq + tablas_der,
        "total_picos": picos_izq + picos_der,
        "tabla_real_izq_cm": tabla_real_izq_cm,
        "tabla_real_der_cm": tabla_real_der_cm,
        "separacion_cm": SEPARACION_TABLAS_CM,
        "pico_izq": pico_izq,
        "pico_der": pico_der
    }


def calcular_un_pano(cortina, metraje_asignado, pico_maestro_cm=None):
    ancho_riel = float(cortina["ancho_riel"])
    apertura = cortina.get("apertura", "Lateral")

    visible = ancho_riel
    trabajo = visible + DOBLADILLO_TOTAL_M

    tablas, picos = tablas_y_picos(visible)
    tabla_real_cm = ancho_tabla_real_cm(visible, tablas)

    if pico_maestro_cm is not None:
        pico = pico_maestro_cm
        metraje_asignado = trabajo + ((pico_maestro_cm * picos) / 100)
        fruncido_real = metraje_asignado / trabajo if trabajo > 0 else 0
    else:
        if trabajo <= 0:
            fruncido_real = 0
        else:
            fruncido_real = metraje_asignado / trabajo

        excedente = metraje_asignado - trabajo
        pico = (excedente * 100) / picos if picos > 0 else 0

    return {
        "tipo": apertura,
        "ancho_riel": ancho_riel,
        "visible": visible,
        "trabajo": trabajo,
        "corte_total": metraje_asignado,
        "fruncido_real": fruncido_real,
        "tablas": tablas,
        "picos": picos,
        "tabla_real_cm": tabla_real_cm,
        "separacion_cm": SEPARACION_TABLAS_CM,
        "pico": pico
    }


# =====================================================
# HTML VISUAL COSTURERO
# =====================================================

def render_html(html, height=500):
    components.html(html, height=height, scrolling=False)


def css_costurero():
    return """
    <style>
    body {
        margin: 0;
        font-family: Arial, Helvetica, sans-serif;
        background: transparent;
    }
    .costurero-panel {
        background: #f8fafc;
        border: 3px solid #0f172a;
        border-radius: 18px;
        padding: 22px;
        box-shadow: 0px 6px 18px rgba(15, 23, 42, 0.15);
        color: #0f172a;
    }
    .costurero-titulo {
        font-size: 26px;
        font-weight: 900;
        text-align: center;
        margin-bottom: 10px;
        letter-spacing: 0.5px;
    }
    .costurero-subtitulo {
        font-size: 18px;
        font-weight: 800;
        text-align: center;
        color: #334155;
        margin-bottom: 18px;
    }
    .costurero-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 14px;
    }
    .costurero-card {
        background: white;
        border: 2px solid #cbd5e1;
        border-radius: 16px;
        padding: 16px;
        text-align: center;
    }
    .icono {
        font-size: 34px;
        margin-bottom: 8px;
    }
    .label {
        font-size: 13px;
        font-weight: 800;
        color: #475569;
    }
    .valor {
        font-size: 30px;
        font-weight: 900;
        color: #111827;
        margin-top: 6px;
    }
    .costurero-detalle {
        margin-top: 18px;
        background: #ffffff;
        border: 2px dashed #94a3b8;
        border-radius: 14px;
        padding: 16px;
        color: #0f172a;
        font-size: 17px;
        line-height: 1.6;
    }
    .costurero-alerta {
        margin-top: 18px;
        background: #fff7ed;
        border: 2px solid #fb923c;
        border-radius: 14px;
        padding: 14px;
        color: #7c2d12;
        font-weight: 900;
        text-align: center;
        font-size: 18px;
    }
    .costurero-error {
        margin-top: 18px;
        background: #fef2f2;
        border: 2px solid #ef4444;
        border-radius: 14px;
        padding: 14px;
        color: #991b1b;
        font-weight: 900;
        text-align: center;
        font-size: 18px;
    }
    @media (max-width: 900px) {
        .costurero-grid {
            grid-template-columns: repeat(2, 1fr);
        }
    }
    </style>
    """


def panel_un_pano(res):
    html = f"""
    {css_costurero()}
    <div class="costurero-panel">
        <div class="costurero-titulo">✂️ HOJA DE CORTE PARA COSTURERO</div>
        <div class="costurero-subtitulo">Apertura: {res['tipo']} | Un solo paño</div>

        <div class="costurero-grid">
            <div class="costurero-card">
                <div class="icono">✂️</div>
                <div class="label">CORTE TOTAL</div>
                <div class="valor">{res['corte_total']:.2f} m</div>
            </div>
            <div class="costurero-card">
                <div class="icono">📏</div>
                <div class="label">ANCHO VISIBLE</div>
                <div class="valor">{res['visible']:.2f} m</div>
            </div>
            <div class="costurero-card">
                <div class="icono">🧵</div>
                <div class="label">TABLAS</div>
                <div class="valor">{res['tablas']}</div>
            </div>
            <div class="costurero-card">
                <div class="icono">🔺</div>
                <div class="label">PICOS / PINZAS</div>
                <div class="valor">{res['picos']}</div>
            </div>
        </div>

        <div class="costurero-detalle">
            <b>📌 Datos indispensables:</b><br>
            Ancho técnico con dobladillos: <b>{res['trabajo']:.2f} m</b><br>
            Tabla real aproximada: <b>{res.get('tabla_real_cm', res['separacion_cm']):.2f} cm</b><br>
            Profundidad de cada pico / pinza: <b>{res['pico']:.2f} cm</b><br>
            Fruncido real: <b>{res['fruncido_real']:.2f}</b>
        </div>

        <div class="costurero-alerta">
            ⚠️ La tabla se ajusta cerca de 10 cm para empezar y terminar en tabla.
        </div>
    </div>
    """
    render_html(html, height=430)


def panel_pano(nombre, corte, visible, tecnico, tablas, picos, separacion, pico, fruncido, lleva_solapa):
    html = f"""
    {css_costurero()}
    <div class="costurero-panel">
        <div class="costurero-titulo">✂️ HOJA DE CORTE - {nombre.upper()}</div>
        <div class="costurero-subtitulo">¿Lleva solapa?: {lleva_solapa}</div>

        <div class="costurero-grid">
            <div class="costurero-card">
                <div class="icono">✂️</div>
                <div class="label">CORTE DEL PAÑO</div>
                <div class="valor">{corte:.2f} m</div>
            </div>
            <div class="costurero-card">
                <div class="icono">📏</div>
                <div class="label">ANCHO VISIBLE</div>
                <div class="valor">{visible:.2f} m</div>
            </div>
            <div class="costurero-card">
                <div class="icono">🧵</div>
                <div class="label">TABLAS</div>
                <div class="valor">{tablas}</div>
            </div>
            <div class="costurero-card">
                <div class="icono">🔺</div>
                <div class="label">PICOS / PINZAS</div>
                <div class="valor">{picos}</div>
            </div>
        </div>

        <div class="costurero-detalle">
            <b>📌 Datos indispensables:</b><br>
            Ancho técnico con dobladillos: <b>{tecnico:.2f} m</b><br>
            Tabla real aproximada: <b>{float(separacion):.2f} cm</b><br>
            Profundidad de cada pico / pinza: <b>{pico:.2f} cm</b><br>
            Fruncido real: <b>{fruncido:.2f}</b>
        </div>

        <div class="costurero-alerta">
            ⚠️ La tabla se ajusta cerca de 10 cm para cerrar exacto. La solapa cuenta solo si hay cruce.
        </div>
    </div>
    """
    render_html(html, height=430)


def panel_error(texto):
    html = f"""
    {css_costurero()}
    <div class="costurero-error">
        🚨 {texto}
    </div>
    """
    render_html(html, height=100)


# =====================================================
# VISUALIZACIÓN DE CORTINA
# =====================================================

def bloque_reglas_costurero(cortina):
    apertura = cortina.get("apertura", "Central")
    tipo_trabajo = cortina.get("tipo_trabajo", "Vertical")
    hay_cruce = cortina.get("hay_cruce", apertura == "Central")

    solapa_texto = (
        "SÍ lleva solapa porque hay cruce entre paños."
        if hay_solapa_real(apertura, hay_cruce)
        else "NO lleva solapa porque no hay cruce entre paños."
    )

    st.markdown(f"""
    <div class="important-box">
        🧵 REGLAS PARA NO COMETER ERRORES<br><br>
        1. La tabla objetivo es <b>{SEPARACION_TABLAS_CM} cm</b>, pero puede ajustarse apenas para cerrar exacto.<br>
        2. La cortina debe empezar en tabla y terminar en tabla.<br>
        3. Si la medida visible no es múltiplo de 10, se calcula una tabla real cercana a 10 cm.<br>
        4. El dobladillo lateral de {DOBLADILLO_LATERAL_CM} cm por lado NO agrega tablas.<br>
        5. La solapa NO depende de si el trabajo es vertical o apaisado.<br>
        6. La solapa depende únicamente de si hay cruce entre paños.<br><br>
        <b>Tipo de trabajo:</b> {tipo_trabajo}<br>
        <b>Apertura:</b> {apertura}<br>
        <b>Solapa:</b> {solapa_texto}
    </div>
    """, unsafe_allow_html=True)


def mostrar_hoja_cortina(cortina, tela, fruncido_uniforme):
    normalizar_cortina(cortina)

    alto_corte = float(cortina["alto_terminado"]) + (
        (float(cortina["cabezal_cm"]) + float(cortina["ruedo_cm"])) / 100
    )

    metraje_teorico = calcular_metraje_cortina(
        cortina,
        tela["solapa_cm"],
        fruncido_uniforme
    )

    metraje_asignado = float(cortina.get("metraje_asignado", metraje_teorico))

    datos_lote = calcular_pico_maestro_lote(tela)
    pico_maestro_cm = datos_lote.get("pico_maestro_cm")

    st.markdown(f"### 🪟 {cortina['ambiente']}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ancho riel", f"{float(cortina['ancho_riel']):.2f} m")
    c2.metric("Alto terminado", f"{float(cortina['alto_terminado']):.2f} m")
    c3.metric("Altura de corte", f"{alto_corte:.2f} m")
    c4.metric("Metraje asignado", f"{metraje_asignado:.2f} m")

    bloque_reglas_costurero(cortina)

    if cortina["tipo_trabajo"] == "Apaisado":
        st.markdown("""
        <div class="info-box">
            📐 TRABAJO APAISADO:<br>
            Verificar orientación del dibujo, trama, pelo o brillo antes de cortar.
            La solapa se aplica igual: solo si hay cruce entre paños.
        </div>
        """, unsafe_allow_html=True)

    if cortina["apertura"] == "Central":
        res = calcular_central(cortina, tela["solapa_cm"], metraje_asignado, pico_maestro_cm)

        suma_panos = res["ancho_izq_sobre_riel"] + res["ancho_der_sobre_riel"]

        if abs(suma_panos - res["ancho_riel"]) > 0.01:
            panel_error(
                f"ATENCIÓN: La suma de paños es {suma_panos:.2f} m, "
                f"pero el riel mide {res['ancho_riel']:.2f} m. Revisar antes de cortar."
            )

        st.markdown(f"""
        <div class="ok-box">
            ✅ RESUMEN CENTRAL<br>
            Total tablas: <b>{res['total_tablas']}</b> |
            Total picos / pinzas: <b>{res['total_picos']}</b><br>
            Tabla real izq.: <b>{res['tabla_real_izq_cm']:.2f} cm</b> |
            Tabla real der.: <b>{res['tabla_real_der_cm']:.2f} cm</b><br>
            Paño con solapa: <b>{res['pano_solapa'] if res['hay_cruce'] else 'No corresponde'}</b>
        </div>
        """, unsafe_allow_html=True)

        tab_izq, tab_der = st.tabs(["✂️ Paño izquierdo", "✂️ Paño derecho"])

        with tab_izq:
            lleva_solapa = (
                "SÍ"
                if res["hay_cruce"] and res["pano_solapa"] == "Izquierda"
                else "NO"
            )

            panel_pano(
                "Paño izquierdo",
                res["corte_izq"],
                res["visible_izq"],
                res["trabajo_izq"],
                res["tablas_izq"],
                res["picos_izq"],
                res["tabla_real_izq_cm"],
                res["pico_izq"],
                res["fruncido_real"],
                lleva_solapa
            )

        with tab_der:
            lleva_solapa = (
                "SÍ"
                if res["hay_cruce"] and res["pano_solapa"] == "Derecha"
                else "NO"
            )

            panel_pano(
                "Paño derecho",
                res["corte_der"],
                res["visible_der"],
                res["trabajo_der"],
                res["tablas_der"],
                res["picos_der"],
                res["tabla_real_der_cm"],
                res["pico_der"],
                res["fruncido_real"],
                lleva_solapa
            )

    else:
        res = calcular_un_pano(cortina, metraje_asignado, pico_maestro_cm)
        panel_un_pano(res)




# =====================================================
# BLOQUE 2 - COSTURA / TALLER
# =====================================================

if "vista" not in st.session_state:
    st.session_state.vista = "BLOQUE_1"


def formato_m_cm(valor_m):
    valor_m = float(valor_m)
    return f"{valor_m:.2f} m ({valor_m * 100:.0f} cm)"


def mensaje_taller(i, j):
    mensajes = [
        "🌟 Hola Romina y Bianca. Vamos paso a paso: esta cortina va a quedar impecable.",
        "🧵 Romina y Bianca, tranquilidad y precisión. La hoja está preparada para trabajar seguras.",
        "✨ Buen trabajo, Romina y Bianca. Midiendo con calma, todo sale prolijo.",
        "💪 Romina y Bianca, confíen en su mano de obra. Revisen cada paso y avancen seguras.",
        "👏 Equipo de costura: gracias por la dedicación de siempre. Hoy también sale un trabajo excelente.",
        "📏 Romina y Bianca: medida exacta, costura prolija y resultado profesional. Vamos con todo."
    ]
    return mensajes[(int(i) + int(j)) % len(mensajes)]


def estilo_bloque_taller():
    st.markdown("""
    <style>
    .taller-saludo {
        background: linear-gradient(135deg, #fff7ed 0%, #fffbeb 100%);
        border: 1px solid #fed7aa;
        border-radius: 18px;
        padding: 18px 22px;
        margin: 10px 0 16px 0;
        color: #7c2d12;
        font-size: 22px;
        font-weight: 850;
        line-height: 1.35;
        box-shadow: 0 6px 16px rgba(124, 45, 18, 0.08);
    }
    .taller-encabezado {
        background: linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%);
        border: 1px solid #c7d2fe;
        border-radius: 22px;
        padding: 20px 24px;
        margin-bottom: 14px;
        box-shadow: 0 8px 22px rgba(15, 23, 42, 0.08);
    }
    .taller-titulo {
        font-size: 32px;
        font-weight: 900;
        color: #111827;
        margin-bottom: 4px;
        letter-spacing: 0.2px;
    }
    .taller-subtitulo {
        font-size: 18px;
        color: #475569;
        font-weight: 750;
    }
    .taller-regla {
        background: #ecfdf5;
        border: 1px solid #a7f3d0;
        color: #065f46;
        border-radius: 16px;
        padding: 13px 16px;
        font-size: 18px;
        font-weight: 800;
        margin-bottom: 12px;
        line-height: 1.35;
    }
    .taller-alerta-apaisado {
        background: #eff6ff;
        border: 1px solid #bfdbfe;
        color: #1e3a8a;
        border-radius: 16px;
        padding: 13px 16px;
        font-size: 18px;
        font-weight: 800;
        margin-bottom: 12px;
        line-height: 1.35;
    }
    .taller-seccion {
        background: #ffffff;
        border: 1px solid #dbeafe;
        border-radius: 20px;
        padding: 18px;
        margin: 14px 0;
        box-shadow: 0 6px 18px rgba(15, 23, 42, 0.07);
    }
    .taller-seccion-titulo {
        font-size: 24px;
        font-weight: 900;
        color: #0f172a;
        margin-bottom: 14px;
    }
    .taller-grid-horizontal {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 12px;
    }
    .taller-medidas-grid {
        display: grid;
        grid-template-columns: repeat(7, minmax(0, 1fr));
        gap: 10px;
    }
    .taller-mini-card {
        background: #f8fafc;
        border: 1px solid #cbd5e1;
        border-radius: 16px;
        padding: 14px 12px;
        min-height: 88px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        text-align: center;
    }
    .taller-mini-label {
        color: #475569;
        font-size: 12px;
        font-weight: 900;
        text-transform: uppercase;
        letter-spacing: 0.4px;
        margin-bottom: 7px;
    }
    .taller-mini-valor {
        color: #111827;
        font-size: 20px;
        font-weight: 950;
        line-height: 1.18;
    }
    .taller-pasos-grid {
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 12px;
    }
    .taller-paso-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-top: 7px solid #334155;
        border-radius: 18px;
        padding: 16px 14px;
        min-height: 210px;
        box-shadow: 0 5px 14px rgba(15, 23, 42, 0.06);
    }
    .taller-paso-numero {
        color: #334155;
        font-size: 17px;
        font-weight: 950;
        margin-bottom: 9px;
        letter-spacing: 0.4px;
    }
    .taller-paso-texto {
        color: #111827;
        font-size: 20px;
        font-weight: 850;
        line-height: 1.25;
    }
    .taller-paso-texto small {
        display: block;
        margin-top: 8px;
        color: #475569;
        font-size: 16px;
        font-weight: 750;
        line-height: 1.25;
    }
    .control-rapido {
        background: #f8fafc;
        border: 1px solid #cbd5e1;
        border-radius: 14px;
        padding: 12px 14px;
        color: #0f172a;
        font-weight: 750;
        margin: 10px 0 12px 0;
    }
    .control-rapido-ok {
        border-color: #a7f3d0;
        background: #ecfdf5;
        color: #065f46;
    }
    .control-rapido-error {
        border-color: #fecaca;
        background: #fef2f2;
        color: #991b1b;
    }
    @media (max-width: 1200px) {
        .taller-medidas-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
        .taller-pasos-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 760px) {
        .taller-grid-horizontal { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .taller-medidas-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .taller-pasos-grid { grid-template-columns: 1fr; }
        .taller-titulo { font-size: 27px; }
        .taller-saludo { font-size: 19px; }
        .taller-mini-valor { font-size: 18px; }
        .taller-paso-texto { font-size: 19px; }
    }
    </style>
    """, unsafe_allow_html=True)


def _card(label, value):
    return dedent(f"""
    <div class="taller-mini-card">
        <div class="taller-mini-label">{label}</div>
        <div class="taller-mini-valor">{value}</div>
    </div>
    """).strip()


def bloque_tarjetas(titulo, tarjetas, clase_grid="taller-grid-horizontal"):
    html = f"""
    <div class="taller-seccion">
        <div class="taller-seccion-titulo">{titulo}</div>
        <div class="{clase_grid}">
            {''.join(_card(label, value) for label, value in tarjetas)}
        </div>
    </div>
    """
    st.markdown(dedent(html).strip(), unsafe_allow_html=True)


def bloque_datos_generales(cliente, telefono, fecha, tela, cortina):
    tarjetas = [
        ("Cliente", cliente if cliente else "Sin cargar"),
        ("Teléfono", telefono if telefono else "Sin cargar"),
        ("Fecha", fecha if fecha else "Sin cargar"),
        ("Tela", tela.get("nombre", "Tela")),
        ("Color", tela.get("color", "Sin cargar") if tela.get("color", "") else "Sin cargar"),
        ("Ambiente", cortina.get("ambiente", "Cortina")),
        ("Trabajo", cortina.get("tipo_trabajo", "Vertical")),
        ("Apertura", cortina.get("apertura", "Central")),
    ]
    bloque_tarjetas("📋 Datos de cliente y cortina", tarjetas)


def bloque_medidas_pano(nombre, corte, tecnico, visible, tablas, picos, profundidad_pico, lleva_solapa, tabla_real_cm=None):
    if tabla_real_cm is None:
        tabla_real_cm = ancho_tabla_real_cm(visible, tablas)
    tarjetas = [
        ("Corte", formato_m_cm(corte)),
        ("Ancho técnico", formato_m_cm(tecnico)),
        ("Medida visible", formato_m_cm(visible)),
        ("Tabla real", f"{tabla_real_cm:.2f} cm"),
        ("Tablas", f"{tablas}"),
        ("Picos", f"{picos}"),
        ("Profundidad del pico", f"{profundidad_pico:.2f} cm"),
        ("Solapa", lleva_solapa),
    ]
    bloque_tarjetas(f"📏 Medidas de trabajo - {nombre}", tarjetas, "taller-medidas-grid")


def bloque_pasos_pano(nombre, corte, tecnico, visible, profundidad_pico, tabla_real_cm=None):
    if tabla_real_cm is None:
        tablas_tmp, _ = tablas_y_picos(visible)
        tabla_real_cm = ancho_tabla_real_cm(visible, tablas_tmp)
    # PASO 3 corregido:
    # Luego de cortar y hacer dobladillo de 4 cm por lado,
    # la medida de control de dobladillo a dobladillo es el corte total menos 8 cm.
    # No se usa el ancho técnico en este paso, porque el control se hace sobre la tela cortada sin entablar.
    medida_control_dobladillo = max(float(corte) - DOBLADILLO_TOTAL_M, 0)

    pasos = [
        ("✂️ PASO 1", f"Cortar la tela a {formato_m_cm(corte)}.", ""),
        ("🧵 PASO 2", f"Realizar dobladillo de {DOBLADILLO_LATERAL_CM} cm por lado.", ""),
        (
            "📏 PASO 3",
            "Medir desde el inicio de un dobladillo hasta el otro extremo del dobladillo.",
            f"Si la tela tiene {formato_m_cm(medida_control_dobladillo)}, continuar con el paso 4."
        ),
        (
            "📐 PASO 4",
            f"Entablar con tablas de {tabla_real_cm:.2f} cm aprox. y picos de {profundidad_pico:.2f} cm de profundidad.",
            ""
        ),
        ("✅ PASO 5", f"Medir la cortina y verificar que posee {formato_m_cm(visible)} de medida visible.", ""),
    ]

    cards = ""
    for numero, texto, detalle in pasos:
        detalle_html = f"<small>{detalle}</small>" if detalle else ""
        cards += dedent(f"""
        <div class="taller-paso-card">
            <div class="taller-paso-numero">{numero}</div>
            <div class="taller-paso-texto">{texto}{detalle_html}</div>
        </div>
        """).strip()

    html = f"""
    <div class="taller-seccion">
        <div class="taller-seccion-titulo">🧵 Paso a paso - {nombre}</div>
        <div class="taller-pasos-grid">{cards}</div>
    </div>
    """
    st.markdown(dedent(html).strip(), unsafe_allow_html=True)


def control_rapido_cortina(cortina, tela):
    """Control mínimo para BLOQUE 1. No modifica datos ni fórmulas."""
    normalizar_cortina(cortina)
    apertura = cortina.get("apertura", "Central")
    hay_cruce = bool(cortina.get("hay_cruce", apertura == "Central"))
    solapa = "Sí" if hay_solapa_real(apertura, hay_cruce) else "No"

    if apertura == "Central":
        ancho_riel = float(cortina.get("ancho_riel", 0.0))
        izq = float(cortina.get("ancho_pano_izq", 0.0))
        der = float(cortina.get("ancho_pano_der", 0.0))
        suma = izq + der
        if abs(suma - ancho_riel) > 0.01:
            st.markdown(
                f"""
                <div class="control-rapido control-rapido-error">
                    ⚠️ Control rápido: la suma de paños es <b>{suma:.2f} m</b>, pero el riel mide <b>{ancho_riel:.2f} m</b>. Revisar antes de enviar a taller.
                </div>
                """,
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f"""
                <div class="control-rapido control-rapido-ok">
                    ✅ Control rápido: riel <b>{ancho_riel:.2f} m</b> | paños <b>{izq:.2f} + {der:.2f} m</b> | cruce: <b>{'Sí' if hay_cruce else 'No'}</b> | solapa: <b>{solapa}</b>.
                </div>
                """,
                unsafe_allow_html=True
            )
    else:
        st.markdown(
            f"""
            <div class="control-rapido control-rapido-ok">
                ✅ Control rápido: apertura <b>{apertura}</b> | un solo paño | solapa: <b>No</b>.
            </div>
            """,
            unsafe_allow_html=True
        )


def mostrar_bloque_taller():
    estilo_bloque_taller()

    if st.button("⬅️ Volver al BLOQUE 1 - Carga de orden"):
        st.session_state.vista = "BLOQUE_1"
        st.rerun()

    i = st.session_state.get("tela_seleccionada", None)
    j = st.session_state.get("cortina_seleccionada", None)

    if i is None or j is None:
        st.warning("No hay una cortina seleccionada para taller. Volvé al BLOQUE 1 y elegí una cortina.")
        return

    try:
        tela = st.session_state.data["telas"][int(i)]
        cortina = tela["cortinas"][int(j)]
    except Exception:
        st.error("No se pudo encontrar la cortina seleccionada. Volvé al BLOQUE 1 y seleccioná nuevamente.")
        return

    normalizar_cortina(cortina)

    alto_corte = float(cortina["alto_terminado"]) + (
        (float(cortina["cabezal_cm"]) + float(cortina["ruedo_cm"])) / 100
    )

    metraje_teorico = calcular_metraje_cortina(
        cortina,
        tela["solapa_cm"],
        tela["fruncido_deseado"]
    )
    metraje_asignado = float(cortina.get("metraje_asignado", metraje_teorico))

    datos_lote = calcular_pico_maestro_lote(tela)
    pico_maestro_cm = datos_lote.get("pico_maestro_cm")

    apertura = cortina.get("apertura", "Central")
    hay_cruce = bool(cortina.get("hay_cruce", apertura == "Central"))
    lleva_solapa_real = hay_solapa_real(apertura, hay_cruce)
    solapa_real_texto = (
        f"SÍ, {float(tela.get('solapa_cm', SOLAPA_DEFAULT_CM)):.0f} cm"
        if lleva_solapa_real
        else "NO"
    )

    st.markdown(
        f"""
        <div class="taller-saludo">{mensaje_taller(i, j)}</div>
        <div class="taller-encabezado">
            <div class="taller-titulo">🧵 BLOQUE 2 - COSTURA / TALLER</div>
            <div class="taller-subtitulo">Vista individual de trabajo: {cortina.get('ambiente', 'Cortina')}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        """
        <div class="taller-regla">
            ✅ Regla de oro: la solapa NO depende de si el trabajo es vertical o apaisado. La solapa depende solamente de si hay cruce entre paños.
        </div>
        """,
        unsafe_allow_html=True
    )

    if cortina.get("tipo_trabajo", "Vertical") == "Apaisado":
        st.markdown(
            """
            <div class="taller-alerta-apaisado">
                📐 Atención trabajo apaisado: verificar orientación del dibujo, trama, pelo o brillo antes de cortar. Esta advertencia no modifica la regla de solapa.
            </div>
            """,
            unsafe_allow_html=True
        )

    bloque_datos_generales(
        st.session_state.data.get("cliente", ""),
        st.session_state.data.get("telefono", ""),
        st.session_state.data.get("fecha", ""),
        tela,
        cortina
    )

    if apertura == "Central":
        res = calcular_central(cortina, tela["solapa_cm"], metraje_asignado, pico_maestro_cm)

        suma_panos = res["ancho_izq_sobre_riel"] + res["ancho_der_sobre_riel"]
        if abs(suma_panos - res["ancho_riel"]) > 0.01:
            st.error(
                f"ATENCIÓN: La suma de paños es {suma_panos:.2f} m, pero el riel mide {res['ancho_riel']:.2f} m. Revisar antes de cortar."
            )

        tab_izq, tab_der = st.tabs(["✂️ Paño izquierdo", "✂️ Paño derecho"])

        with tab_izq:
            lleva_solapa = "SÍ" if res["hay_cruce"] and res["pano_solapa"] == "Izquierda" else "NO"
            bloque_medidas_pano(
                "Paño izquierdo",
                res["corte_izq"],
                res["trabajo_izq"],
                res["visible_izq"],
                res["tablas_izq"],
                res["picos_izq"],
                res["pico_izq"],
                lleva_solapa,
                res["tabla_real_izq_cm"]
            )
            bloque_pasos_pano(
                "Paño izquierdo",
                res["corte_izq"],
                res["trabajo_izq"],
                res["visible_izq"],
                res["pico_izq"],
                res["tabla_real_izq_cm"]
            )

        with tab_der:
            lleva_solapa = "SÍ" if res["hay_cruce"] and res["pano_solapa"] == "Derecha" else "NO"
            bloque_medidas_pano(
                "Paño derecho",
                res["corte_der"],
                res["trabajo_der"],
                res["visible_der"],
                res["tablas_der"],
                res["picos_der"],
                res["pico_der"],
                lleva_solapa,
                res["tabla_real_der_cm"]
            )
            bloque_pasos_pano(
                "Paño derecho",
                res["corte_der"],
                res["trabajo_der"],
                res["visible_der"],
                res["pico_der"],
                res["tabla_real_der_cm"]
            )

    else:
        res = calcular_un_pano(cortina, metraje_asignado, pico_maestro_cm)
        bloque_medidas_pano(
            "Paño único",
            res["corte_total"],
            res["trabajo"],
            res["visible"],
            res["tablas"],
            res["picos"],
            res["pico"],
            solapa_real_texto,
            res.get("tabla_real_cm")
        )
        bloque_pasos_pano(
            "Paño único",
            res["corte_total"],
            res["trabajo"],
            res["visible"],
            res["pico"],
            res.get("tabla_real_cm")
        )



# =====================================================
# BLOQUE 0 - ESCÁNER IA MASIVO DE ÓRDENES MORO
# =====================================================

MODELO_GEMINI = "gemini-2.5-flash"
MAX_LADO_IMAGEN_IA = 1600
CALIDAD_JPEG_IA = 72
TAMANIO_LOTE_IA_DEFAULT = 5


def obtener_api_key_gemini():
    """Busca la clave en Render/variables de entorno y también en Secrets de Streamlit."""
    claves = ["GOOGLE_API_KEY", "GEMINI_KEY"]

    for nombre in claves:
        valor = os.environ.get(nombre, "")
        if valor:
            return valor

    try:
        for nombre in claves:
            if nombre in st.secrets and st.secrets[nombre]:
                return st.secrets[nombre]
    except Exception:
        pass

    return ""


def configurar_gemini():
    if genai is None:
        st.error("No está instalada la librería google-generativeai. Revisá requirements.txt.")
        return False

    api_key = obtener_api_key_gemini()
    if not api_key:
        st.error(
            "Falta configurar la clave de Gemini. En Render cargá GOOGLE_API_KEY y GEMINI_KEY "
            "con la misma clave."
        )
        return False

    genai.configure(api_key=api_key)
    return True


def extraer_json_desde_texto(texto):
    """Extrae JSON aunque Gemini lo devuelva entre ```json ... ``` o con texto alrededor.

    Puede devolver un diccionario o una lista. En V7 se usa especialmente para
    leer tandas de varias fotos en una sola respuesta JSON array.
    """
    if texto is None:
        return {}

    limpio = str(texto).strip()
    limpio = limpio.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(limpio)
    except Exception:
        pass

    # Primero intentar array completo: [ {...}, {...} ]
    match_array = re.search(r"\[.*\]", limpio, flags=re.DOTALL)
    if match_array:
        try:
            return json.loads(match_array.group(0))
        except Exception:
            pass

    # Después intentar objeto simple: { ... }
    match_obj = re.search(r"\{.*\}", limpio, flags=re.DOTALL)
    if match_obj:
        try:
            return json.loads(match_obj.group(0))
        except Exception:
            return {}

    return {}


def numero_seguro(valor, default=0.0):
    """Convierte 1,75 / '1.75 m' / '$ 1.75' a float seguro."""
    if valor is None:
        return float(default)
    if isinstance(valor, (int, float)):
        try:
            return float(valor)
        except Exception:
            return float(default)

    texto = str(valor).strip()
    if not texto:
        return float(default)

    texto = texto.replace("m2", "").replace("mts", "").replace("mt", "").replace("m", "")
    texto = texto.replace(" ", "").replace(",", ".")
    texto = re.sub(r"[^0-9.\-]", "", texto)

    if texto.count(".") > 1:
        partes = texto.split(".")
        texto = "".join(partes[:-1]) + "." + partes[-1]

    try:
        return float(texto)
    except Exception:
        return float(default)


def texto_seguro(valor, default=""):
    if valor is None:
        return default
    if isinstance(valor, float) and pd.isna(valor):
        return default
    texto = str(valor).strip()
    if texto.lower() in ["nan", "none", "null"]:
        return default
    return texto


def clave_texto_lote(valor):
    """Normaliza texto para comparar lotes/telas sin confundir Lote 1 con Lote 10."""
    texto = texto_seguro(valor).lower().strip()
    reemplazos = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n",
        "º": "", "°": ""
    }
    for a, b in reemplazos.items():
        texto = texto.replace(a, b)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def lote_coincide_en_texto(lote_txt, texto):
    lote_norm = clave_texto_lote(lote_txt)
    texto_norm = clave_texto_lote(texto)
    if not lote_norm or not texto_norm:
        return False
    # coincidencia por token completo; evita que lote 1 coincida con lote 10.
    patron = r"(^|[^0-9a-z])" + re.escape(lote_norm) + r"([^0-9a-z]|$)"
    return bool(re.search(patron, texto_norm))


def normalizar_apertura(valor):
    texto = texto_seguro(valor).lower()
    texto = texto.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")

    if "central" in texto or "centro" in texto or "medio" in texto:
        return "Central"
    if "izq" in texto or "izquierda" in texto:
        return "Izquierda"
    if "der" in texto or "derecha" in texto:
        return "Derecha"
    if "lateral" in texto or "un pa" in texto or "unico" in texto or "único" in texto:
        return "Lateral"

    return "Central"


def normalizar_trabajo(valor):
    texto = texto_seguro(valor).lower()
    texto = texto.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")

    if "apais" in texto or "horizontal" in texto:
        return "Apaisado"
    return "Vertical"


def clave_lote_desde_orden(orden):
    """
    Clave SEGURA para agrupar órdenes antes de cargar al programa.

    Regla aprobada para taller:
    - Si la orden trae LOTE, el LOTE manda. No se separa por pequeñas diferencias
      de tela/color leídas por IA, porque eso parte el mismo lote y puede hacer
      que el sistema calcule mal los metros recibidos.
    - Solo si NO hay lote, se agrupa por tela + color.
    """
    lote = texto_seguro(orden.get("lote"))
    tela = texto_seguro(orden.get("nombre_tela"))
    color = texto_seguro(orden.get("color_tela"))

    if lote:
        return f"LOTE: {lote}"

    partes = []
    if tela:
        partes.append(f"TELA: {tela}")
    if color:
        partes.append(f"COLOR: {color}")

    if not partes:
        return ""

    return " | ".join(partes)


def etiqueta_lote_para_mostrar(clave, filas):
    """Etiqueta visual más completa para la tabla de auditoría."""
    if not filas:
        return clave

    lote = texto_seguro(filas[0].get("lote"))
    telas = sorted({texto_seguro(o.get("nombre_tela")) for o in filas if texto_seguro(o.get("nombre_tela"))})
    colores = sorted({texto_seguro(o.get("color_tela")) for o in filas if texto_seguro(o.get("color_tela"))})

    partes = []
    if lote:
        partes.append(f"LOTE: {lote}")
    elif clave:
        partes.append(clave)

    if telas:
        partes.append("Tela: " + ", ".join(telas[:3]) + ("..." if len(telas) > 3 else ""))
    if colores:
        partes.append("Color: " + ", ".join(colores[:3]) + ("..." if len(colores) > 3 else ""))

    return " | ".join(partes) if partes else clave


def evaluar_estado_orden(orden):
    motivos = []

    if not clave_lote_desde_orden(orden):
        motivos.append("Falta lote/tela/color")
    if numero_seguro(orden.get("ancho_riel")) <= 0:
        motivos.append("Falta ancho")
    if numero_seguro(orden.get("alto_terminado")) <= 0:
        motivos.append("Falta alto")
    if numero_seguro(orden.get("metraje_corte")) <= 0:
        motivos.append("Falta metraje/corte")
    if normalizar_apertura(orden.get("apertura")) not in APERTURAS:
        motivos.append("Apertura dudosa")
    if normalizar_trabajo(orden.get("uso")) not in TIPOS_TRABAJO:
        motivos.append("Trabajo dudoso")

    if motivos:
        return "REVISAR", "; ".join(motivos)

    return "OK", ""


def normalizar_orden_detectada(raw, nombre_archivo):
    if not isinstance(raw, dict):
        raw = {}

    orden = {
        "cargar": False,
        "estado": "REVISAR",
        "archivo": nombre_archivo,
        "numero_orden": texto_seguro(raw.get("numero_orden") or raw.get("orden") or raw.get("nro_orden")),
        "cliente": texto_seguro(raw.get("cliente")),
        "telefono": texto_seguro(raw.get("telefono")),
        "lote": texto_seguro(raw.get("lote") or raw.get("numero_lote") or raw.get("nro_lote")),
        "nombre_tela": texto_seguro(raw.get("nombre_tela") or raw.get("tela") or raw.get("tipo_tela")),
        "color_tela": texto_seguro(raw.get("color_tela") or raw.get("color")),
        "metros_recibidos": numero_seguro(raw.get("metros_recibidos") or raw.get("metros_tela") or raw.get("metros_totales_lote") or raw.get("metros_enviados"), 0.0),
        "origen_metros": "Oficina" if numero_seguro(raw.get("metros_recibidos") or raw.get("metros_tela") or raw.get("metros_totales_lote") or raw.get("metros_enviados"), 0.0) > 0 else "",
        "ambiente": texto_seguro(raw.get("ambiente") or raw.get("cortina") or raw.get("habitacion"), "Cortina"),
        "ancho_riel": numero_seguro(raw.get("ancho_riel") or raw.get("ancho_cortina") or raw.get("ancho"), 0.0),
        "alto_terminado": numero_seguro(raw.get("alto_terminado") or raw.get("alto") or raw.get("altura"), 0.0),
        "altura_corte_oficina": numero_seguro(raw.get("altura_corte") or raw.get("alto_corte") or raw.get("altura_de_corte"), 0.0),
        "metraje_corte": numero_seguro(raw.get("metraje_corte") or raw.get("corte_exacto") or raw.get("corte") or raw.get("metraje"), 0.0),
        "apertura": normalizar_apertura(raw.get("apertura")),
        "uso": normalizar_trabajo(raw.get("uso") or raw.get("tipo_trabajo") or raw.get("trabajo")),
        "observaciones": texto_seguro(raw.get("observaciones") or raw.get("nota") or raw.get("detalle")),
    }

    estado, motivo = evaluar_estado_orden(orden)
    orden["estado"] = estado
    orden["motivo_revision"] = motivo
    orden["cargar"] = estado == "OK"
    return orden



def optimizar_imagen_para_ia(archivo, max_lado=MAX_LADO_IMAGEN_IA, calidad=CALIDAD_JPEG_IA):
    """Achica y comprime una foto antes de enviarla a Gemini.

    Objetivo práctico:
    - Que las fotos del celular carguen mejor.
    - Que cada consulta pese menos.
    - Evitar mandar imágenes enormes de WhatsApp/cámara cuando solo necesitamos leer texto.

    Devuelve: (imagen_pil_optimizada, info)
    """
    nombre = getattr(archivo, "name", "orden")
    try:
        archivo.seek(0)
    except Exception:
        pass

    imagen = Image.open(archivo)
    imagen = ImageOps.exif_transpose(imagen).convert("RGB")

    ancho_original, alto_original = imagen.size
    bytes_originales = None
    try:
        bytes_originales = len(archivo.getvalue())
    except Exception:
        pass

    # thumbnail conserva proporción y evita agrandar imágenes chicas.
    imagen.thumbnail((max_lado, max_lado), Image.Resampling.LANCZOS)

    buffer = BytesIO()
    imagen.save(buffer, format="JPEG", quality=int(calidad), optimize=True)
    bytes_optimizados = buffer.tell()
    buffer.seek(0)

    imagen_optimizada = Image.open(buffer).convert("RGB")
    # Cargamos la imagen en memoria para que no dependa del buffer después.
    imagen_optimizada.load()

    info = {
        "archivo": nombre,
        "ancho_original": ancho_original,
        "alto_original": alto_original,
        "ancho_optimizado": imagen_optimizada.size[0],
        "alto_optimizado": imagen_optimizada.size[1],
        "kb_original": round(bytes_originales / 1024, 1) if bytes_originales else None,
        "kb_optimizado": round(bytes_optimizados / 1024, 1),
    }
    return imagen_optimizada, info


def construir_prompt_ordenes_moro(cantidad=1):
    modo = "una imagen" if cantidad == 1 else f"{cantidad} imágenes"
    return f"""
    Analizá {modo} de órdenes/hojas de producción de cortinas de la empresa MORO.

    Tu tarea es extraer datos para un sistema de corte y armado de cortinas.
    Respondé SOLO un JSON puro, sin markdown, sin explicación y sin texto adicional.

    IMPORTANTE PARA TANDAS:
    - Devolvé SIEMPRE un ARRAY JSON.
    - El array debe tener exactamente {cantidad} objeto/s, uno por cada imagen recibida.
    - Respetá el mismo orden de las imágenes: imagen 1 = primer objeto, imagen 2 = segundo objeto, etc.
    - Si una imagen no se puede leer, devolvé el objeto igual con los campos dudosos en null y una observación.

    Usá estas claves exactas en cada objeto:
    {{
      "numero_orden": "número de orden si aparece; si no aparece, null",
      "cliente": "cliente si aparece; si no aparece, null",
      "telefono": "teléfono si aparece; si no aparece, null",
      "lote": "número o nombre de lote si aparece; si no aparece, null",
      "nombre_tela": "nombre/tipo de tela si aparece; si no aparece, null",
      "color_tela": "color de tela si aparece; si no aparece, null",
      "metros_recibidos": "metros totales de tela enviados/recibidos para ese lote si aparece; si no aparece, null",
      "ambiente": "nombre del ambiente o texto después de Cortina 1, Cortina 2, etc.",
      "ancho_riel": "valor de Ancho de Cortina / ancho de riel, solo número en metros",
      "alto_terminado": "valor de Alto terminado, solo número en metros",
      "altura_corte": "valor de Altura de corte si aparece, solo número en metros; si no aparece, null",
      "metraje_corte": "valor de Corte exacto de paño x ancho / corte asignado, solo número en metros",
      "apertura": "Central, Derecha, Izquierda o Lateral según figure",
      "uso": "Apaisado o Vertical según figure",
      "observaciones": "aclaraciones útiles visibles; si no hay, null"
    }}

    Reglas:
    - Si un dato no se ve con claridad, poné null.
    - No inventes lote, tela ni color.
    - No conviertas centímetros si el dato principal está en metros; devolvé metros como número.
    - Si aparecen comas decimales, podés devolver número con punto decimal.
    - No confundas metraje_corte con metros_recibidos:
      * metraje_corte = corte asignado a una cortina/paño/trabajo puntual.
      * metros_recibidos = total de metros que administración envía para todo el lote/tela.
    - Si la orden no muestra metros totales del lote, dejá metros_recibidos en null; el sistema lo calculará por suma de cortes al agrupar.
    - IMPORTANTE: solo completá metros_recibidos si ves una frase clara como "metros recibidos", "metros enviados", "total de tela", "total lote" o similar.
    - Si solo ves "corte exacto", "corte de paño", "metraje corte" o un número junto a la cortina, eso va en metraje_corte y NO en metros_recibidos.
    """


def analizar_ordenes_lote_con_ia(imagenes_info):
    """Envía varias fotos optimizadas en UNA sola llamada a Gemini.

    imagenes_info: lista de tuplas (imagen_pil, nombre_archivo)
    Devuelve una lista de órdenes normalizadas, una por imagen.
    """
    if not configurar_gemini():
        return []

    if not imagenes_info:
        return []

    model = genai.GenerativeModel(MODELO_GEMINI)
    prompt = construir_prompt_ordenes_moro(len(imagenes_info))

    contenido = [prompt]
    for idx, (imagen_pil, nombre_archivo) in enumerate(imagenes_info, start=1):
        contenido.append(f"IMAGEN {idx} - archivo: {nombre_archivo}")
        contenido.append(imagen_pil)

    try:
        response = model.generate_content(contenido)
        raw = extraer_json_desde_texto(getattr(response, "text", ""))

        if isinstance(raw, dict):
            # Por si Gemini devuelve un wrapper tipo {"ordenes": [...]}.
            for clave in ["ordenes", "items", "trabajos", "cortinas", "bandeja"]:
                if isinstance(raw.get(clave), list):
                    raw = raw.get(clave)
                    break
            else:
                raw = [raw]

        if not isinstance(raw, list):
            raw = []

        ordenes = []
        for idx, (imagen_pil, nombre_archivo) in enumerate(imagenes_info):
            item = raw[idx] if idx < len(raw) and isinstance(raw[idx], dict) else {}
            ordenes.append(normalizar_orden_detectada(item, nombre_archivo))

        return ordenes

    except Exception as e:
        # No reintentamos una por una automáticamente, para no gastar cupo de más.
        st.error(f"Error al leer tanda de {len(imagenes_info)} foto/s: {e}")
        return [
            normalizar_orden_detectada({"observaciones": f"Error IA en tanda: {e}"}, nombre_archivo)
            for _, nombre_archivo in imagenes_info
        ]

def analizar_orden_con_ia(imagen_pil, nombre_archivo="orden"):
    """Compatibilidad: lee una sola orden usando la misma lógica V7 de tandas."""
    ordenes = analizar_ordenes_lote_con_ia([(imagen_pil, nombre_archivo)])
    return ordenes[0] if ordenes else None


def encontrar_o_crear_lote(orden):
    data = st.session_state.data
    data.setdefault("telas", [])

    lote_txt = texto_seguro(orden.get("lote"))
    nombre_tela = texto_seguro(orden.get("nombre_tela"))
    color_tela = texto_seguro(orden.get("color_tela"))
    metros = numero_seguro(orden.get("metros_recibidos"), 0.0)

    nombre_lote = nombre_tela or lote_txt or "Lote importado"
    color_lote = color_tela

    lote_norm = clave_texto_lote(lote_txt)
    nombre_norm = clave_texto_lote(nombre_lote)
    color_norm = clave_texto_lote(color_lote)

    for tela in data["telas"]:
        tela_lote_id = clave_texto_lote(tela.get("lote_id"))
        tela_nombre_base = clave_texto_lote(tela.get("nombre_tela_base") or tela.get("nombre"))
        tela_color = clave_texto_lote(tela.get("color"))

        if lote_norm:
            # Si la orden trae lote, el lote manda. No alcanza con mismo nombre/color,
            # porque puede haber dos lotes distintos de la misma tela y color.
            coincide = (
                (tela_lote_id and tela_lote_id == lote_norm)
                or (not tela_lote_id and lote_coincide_en_texto(lote_txt, tela.get("nombre")))
            )
        else:
            # Solo cuando no hay lote, agrupamos por nombre de tela + color.
            coincide = (
                tela_nombre_base == nombre_norm
                and (not color_norm or tela_color == color_norm)
            )

        if coincide:
            if metros > 0:
                metros_actuales = float(tela.get("metros_recibidos", 0.0))
                if metros_actuales <= 0 or bool(orden.get("_actualizar_metros_lote")):
                    tela["metros_recibidos"] = metros
                    tela["origen_metros"] = texto_seguro(orden.get("origen_metros"), "Oficina / IA")
            if lote_txt and not tela.get("lote_id"):
                tela["lote_id"] = lote_txt
            if nombre_tela and not tela.get("nombre_tela_base"):
                tela["nombre_tela_base"] = nombre_tela
            if not tela.get("color") and color_lote:
                tela["color"] = color_lote
            tela.setdefault("cortinas", [])
            return tela

    nuevo = {
        "nombre": nombre_lote if not lote_txt else f"{nombre_lote} - Lote {lote_txt}",
        "lote_id": lote_txt,
        "nombre_tela_base": nombre_tela or nombre_lote,
        "color": color_lote,
        "metros_recibidos": metros,
        "origen_metros": texto_seguro(orden.get("origen_metros"), "Oficina / IA") if metros > 0 else "",
        "fruncido_deseado": 2.2,
        "solapa_cm": SOLAPA_DEFAULT_CM,
        "cortinas": []
    }
    data["telas"].append(nuevo)
    return nuevo


def cargar_orden_como_cortina(orden):
    tela = encontrar_o_crear_lote(orden)

    ancho = numero_seguro(orden.get("ancho_riel"), 0.0)
    alto = numero_seguro(orden.get("alto_terminado"), 0.0)
    metraje = numero_seguro(orden.get("metraje_corte"), 0.0)
    apertura = normalizar_apertura(orden.get("apertura"))
    trabajo = normalizar_trabajo(orden.get("uso"))

    if apertura == "Central":
        ancho_izq = round(ancho / 2, 2)
        ancho_der = round(ancho - ancho_izq, 2)
        hay_cruce = True
    else:
        ancho_izq = 0.0
        ancho_der = 0.0
        hay_cruce = False

    ambiente = texto_seguro(orden.get("ambiente"), f"Cortina {len(tela.get('cortinas', [])) + 1}")
    numero_orden = texto_seguro(orden.get("numero_orden"))
    archivo = texto_seguro(orden.get("archivo"))
    observaciones = texto_seguro(orden.get("observaciones"))
    altura_corte_oficina = numero_seguro(orden.get("altura_corte_oficina"), 0.0)

    cortina = {
        "ambiente": ambiente,
        "ancho_riel": ancho,
        "alto_terminado": alto,
        "tipo_trabajo": trabajo,
        "apertura": apertura,
        "cabezal_cm": CABEZAL_DEFAULT_CM,
        "ruedo_cm": RUEDO_DEFAULT_CM,
        "metraje_asignado": metraje,
        "ancho_pano_izq": ancho_izq,
        "ancho_pano_der": ancho_der,
        "hay_cruce": hay_cruce,
        "pano_solapa": "Derecha",
        "origen_ia": True,
        "numero_orden": numero_orden,
        "archivo_origen": archivo,
        "observaciones_ia": observaciones,
        "altura_corte_oficina": altura_corte_oficina,
    }

    tela.setdefault("cortinas", []).append(cortina)
    return cortina, tela


def dataframe_a_ordenes(editado):
    if hasattr(editado, "to_dict"):
        filas = editado.to_dict("records")
    else:
        filas = list(editado)

    ordenes = []
    for fila in filas:
        orden = dict(fila)
        orden["cargar"] = bool(orden.get("cargar"))
        orden["numero_orden"] = texto_seguro(orden.get("numero_orden"))
        orden["cliente"] = texto_seguro(orden.get("cliente"))
        orden["telefono"] = texto_seguro(orden.get("telefono"))
        orden["lote"] = texto_seguro(orden.get("lote"))
        orden["nombre_tela"] = texto_seguro(orden.get("nombre_tela"))
        orden["color_tela"] = texto_seguro(orden.get("color_tela"))
        orden["metros_recibidos"] = numero_seguro(orden.get("metros_recibidos"), 0.0)
        orden["origen_metros"] = texto_seguro(orden.get("origen_metros"))
        orden["ambiente"] = texto_seguro(orden.get("ambiente"), "Cortina")
        orden["ancho_riel"] = numero_seguro(orden.get("ancho_riel"), 0.0)
        orden["alto_terminado"] = numero_seguro(orden.get("alto_terminado"), 0.0)
        orden["altura_corte_oficina"] = numero_seguro(orden.get("altura_corte_oficina"), 0.0)
        orden["metraje_corte"] = numero_seguro(orden.get("metraje_corte"), 0.0)
        orden["apertura"] = normalizar_apertura(orden.get("apertura"))
        orden["uso"] = normalizar_trabajo(orden.get("uso"))
        orden["observaciones"] = texto_seguro(orden.get("observaciones"))
        orden["archivo"] = texto_seguro(orden.get("archivo"))

        estado, motivo = evaluar_estado_orden(orden)
        orden["estado"] = estado
        orden["motivo_revision"] = motivo
        ordenes.append(orden)

    return ordenes


def preparar_metros_automaticos_por_lote(ordenes, solo_tildadas=False):
    """
    Completa metros_recibidos por lote con auditoría.

    Prioridad:
    1) Si administración/IA leyó un TOTAL REAL DEL LOTE, usa ese total.
    2) Si no hay total de lote, calcula metros_recibidos como suma de metraje_corte.
    3) Si la IA confundió metros_recibidos con el corte individual de cada orden,
       descarta esos valores como total de lote y suma los cortes.
    """
    grupos = {}

    for orden in ordenes:
        if solo_tildadas and not bool(orden.get("cargar")):
            continue
        clave = clave_lote_desde_orden(orden)
        if not clave:
            continue
        grupos.setdefault(clave, []).append(orden)

    resumen = []

    for clave, filas in grupos.items():
        suma_cortes = round(sum(numero_seguro(o.get("metraje_corte"), 0.0) for o in filas), 2)

        valores_oficina_filas = []
        for o in filas:
            metros_fila = round(numero_seguro(o.get("metros_recibidos"), 0.0), 2)
            origen_fila = texto_seguro(o.get("origen_metros")).lower()
            if metros_fila > 0 and not origen_fila.startswith("calculado"):
                valores_oficina_filas.append((o, metros_fila))

        valores_oficina = sorted({v for _, v in valores_oficina_filas})

        # Detección de error frecuente:
        # la IA pone en metros_recibidos el mismo valor que el corte de esa orden.
        coincidencias_corte = 0
        for o, metros_fila in valores_oficina_filas:
            corte_fila = round(numero_seguro(o.get("metraje_corte"), 0.0), 2)
            if corte_fila > 0 and abs(metros_fila - corte_fila) <= 0.03:
                coincidencias_corte += 1

        parece_corte_individual = (
            len(filas) > 1
            and coincidencias_corte >= max(1, len(valores_oficina_filas) - 1)
            and valores_oficina_filas
        )

        if parece_corte_individual:
            metros_lote = suma_cortes
            origen = "Calculado por suma de cortes"
            aviso = "La IA parecía usar el corte individual como metros del lote; se corrigió sumando los cortes del grupo."
        elif valores_oficina:
            metros_lote = max(valores_oficina)
            origen = "Oficina"
            if len(valores_oficina) == 1:
                aviso = ""
            else:
                aviso = f"Valores distintos de metros de lote detectados: {valores_oficina}. Se usó el mayor; revisar si son lotes distintos."
        else:
            metros_lote = suma_cortes
            origen = "Calculado por suma de cortes"
            aviso = "No se detectó total de lote; se sumaron los cortes de las órdenes del mismo lote."

        for orden in filas:
            if numero_seguro(orden.get("metros_recibidos"), 0.0) <= 0 or solo_tildadas or parece_corte_individual:
                orden["metros_recibidos"] = metros_lote
                orden["origen_metros"] = origen
            orden["_actualizar_metros_lote"] = solo_tildadas
            if aviso:
                obs = texto_seguro(orden.get("observaciones"))
                if "AUDITORÍA LOTE" not in obs:
                    orden["observaciones"] = (obs + " | " if obs else "") + "AUDITORÍA LOTE: " + aviso

        # Aviso extra: si el grupo se armó por LOTE y la IA trajo variantes de tela/color,
        # no se separa el lote; se informa para que el usuario revise visualmente.
        etiqueta = etiqueta_lote_para_mostrar(clave, filas)
        if clave.startswith("LOTE:"):
            telas_distintas = sorted({texto_seguro(o.get("nombre_tela")) for o in filas if texto_seguro(o.get("nombre_tela"))})
            colores_distintos = sorted({texto_seguro(o.get("color_tela")) for o in filas if texto_seguro(o.get("color_tela"))})
            extras = []
            if len(telas_distintas) > 1:
                extras.append("telas leídas distintas dentro del mismo lote")
            if len(colores_distintos) > 1:
                extras.append("colores leídos distintos dentro del mismo lote")
            if extras:
                aviso_extra = "Mismo lote agrupado correctamente, pero revisar: " + ", ".join(extras) + "."
                aviso = (aviso + " | " if aviso else "") + aviso_extra

        resumen.append({
            "lote_tela_color": etiqueta,
            "cortinas": len(filas),
            "suma_cortes": suma_cortes,
            "metros_lote": metros_lote,
            "origen": origen,
            "aviso": aviso,
        })

    return ordenes, resumen


def plantilla_json_chatgpt():
    """Modelo simple para que ChatGPT devuelva órdenes compatibles con el programa."""
    return [
        {
            "numero_orden": "",
            "cliente": "",
            "telefono": "",
            "lote": "Lote 1",
            "nombre_tela": "Nombre de la tela",
            "color_tela": "Color",
            "metros_recibidos": 0.0,
            "ambiente": "Dormitorio 1",
            "ancho_riel": 0.0,
            "alto_terminado": 0.0,
            "metraje_corte": 0.0,
            "apertura": "Central",
            "uso": "Vertical",
            "observaciones": ""
        }
    ]


def extraer_ordenes_desde_json_chatgpt(payload, nombre_archivo="ordenes_chatgpt.json"):
    """
    Acepta JSON generado por ChatGPT o un respaldo del programa y lo convierte
    en filas de la bandeja de revisión.

    Formatos aceptados:
    1) Lista directa de órdenes: [{...}, {...}]
    2) Diccionario con claves: ordenes, ordenes_detectadas, bandeja, items o trabajos.
    3) Respaldo CastaMuebles con estructura: {cliente, telefono, telas:[{..., cortinas:[...]}]}.
    """
    ordenes = []

    if isinstance(payload, list):
        for idx, raw in enumerate(payload, start=1):
            archivo = f"{nombre_archivo} / fila {idx}"
            ordenes.append(normalizar_orden_detectada(raw, archivo))
        return ordenes

    if not isinstance(payload, dict):
        return []

    cliente_general = texto_seguro(payload.get("cliente") or payload.get("cliente_general"))
    telefono_general = texto_seguro(payload.get("telefono") or payload.get("telefono_general"))

    # Formato respaldo completo del programa: data/telas/cortinas.
    telas = payload.get("telas")
    if isinstance(telas, list):
        for idx_tela, tela in enumerate(telas, start=1):
            if not isinstance(tela, dict):
                continue
            cortinas = tela.get("cortinas", [])
            if not isinstance(cortinas, list):
                continue

            lote_tela = texto_seguro(tela.get("lote") or tela.get("nombre"), f"Lote {idx_tela}")
            nombre_tela = texto_seguro(tela.get("nombre") or tela.get("nombre_tela"), lote_tela)
            color_tela = texto_seguro(tela.get("color") or tela.get("color_tela"))
            metros_lote = numero_seguro(tela.get("metros_recibidos") or tela.get("metros_tela"), 0.0)

            for idx_cortina, cortina in enumerate(cortinas, start=1):
                if not isinstance(cortina, dict):
                    continue
                raw = {
                    "numero_orden": cortina.get("numero_orden") or cortina.get("orden"),
                    "cliente": cliente_general or cortina.get("cliente"),
                    "telefono": telefono_general or cortina.get("telefono"),
                    "lote": lote_tela,
                    "nombre_tela": nombre_tela,
                    "color_tela": color_tela,
                    "metros_recibidos": metros_lote,
                    "ambiente": cortina.get("ambiente"),
                    "ancho_riel": cortina.get("ancho_riel"),
                    "alto_terminado": cortina.get("alto_terminado"),
                    "metraje_corte": cortina.get("metraje_corte") or cortina.get("metraje_asignado"),
                    "apertura": cortina.get("apertura"),
                    "uso": cortina.get("uso") or cortina.get("tipo_trabajo"),
                    "observaciones": cortina.get("observaciones") or cortina.get("nota"),
                }
                archivo = f"{nombre_archivo} / lote {idx_tela} / cortina {idx_cortina}"
                ordenes.append(normalizar_orden_detectada(raw, archivo))
        return ordenes

    # Formatos de bandeja / ChatGPT.
    for clave in ["ordenes", "ordenes_detectadas", "bandeja", "items", "trabajos", "cortinas"]:
        lista = payload.get(clave)
        if isinstance(lista, list):
            for idx, raw in enumerate(lista, start=1):
                if isinstance(raw, dict):
                    raw = dict(raw)
                    raw.setdefault("cliente", cliente_general)
                    raw.setdefault("telefono", telefono_general)
                archivo = f"{nombre_archivo} / {clave} {idx}"
                ordenes.append(normalizar_orden_detectada(raw, archivo))
            return ordenes

    # Si viene una sola orden como diccionario suelto.
    if any(k in payload for k in ["ambiente", "ancho_riel", "ancho_cortina", "alto_terminado", "metraje_corte", "corte"]):
        payload = dict(payload)
        payload.setdefault("cliente", cliente_general)
        payload.setdefault("telefono", telefono_general)
        return [normalizar_orden_detectada(payload, nombre_archivo)]

    return []


def extraer_payload_json_desde_texto(texto):
    """
    Lee JSON pegado como texto. Sirve para WhatsApp/celular:
    tolera texto antes/después y bloques ```json ... ```.
    """
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("No pegaste ningún texto JSON.")

    # Si viene dentro de un bloque markdown, intenta tomar el bloque que empiece con { o [.
    texto_limpio = texto.replace("```json", "```").replace("```JSON", "```").replace("```Json", "```")
    if "```" in texto_limpio:
        partes = texto_limpio.split("```")
        for parte in partes:
            candidato = parte.strip()
            if candidato.startswith("{") or candidato.startswith("["):
                texto_limpio = candidato
                break

    # Si WhatsApp agregó título, mensaje o firmas, recorta desde el primer JSON al último cierre.
    posiciones_inicio = [pos for pos in [texto_limpio.find("{"), texto_limpio.find("[")] if pos >= 0]
    if posiciones_inicio:
        inicio = min(posiciones_inicio)
        fin = max(texto_limpio.rfind("}"), texto_limpio.rfind("]"))
        if fin > inicio:
            texto_limpio = texto_limpio[inicio:fin + 1]

    return json.loads(texto_limpio)


def leer_json_subido(uploaded_file):
    """Lee archivo JSON/TXT subido desde Streamlit, tolerando BOM UTF-8."""
    contenido = uploaded_file.getvalue().decode("utf-8-sig")
    return extraer_payload_json_desde_texto(contenido)


def normalizar_payload_importado(payload, origen="importacion_chatgpt"):
    """Convierte cualquier payload aceptado en órdenes listas para bandeja."""
    ordenes_importadas = extraer_ordenes_desde_json_chatgpt(payload, origen)
    ordenes_importadas, _ = preparar_metros_automaticos_por_lote(ordenes_importadas, solo_tildadas=False)
    return ordenes_importadas


def mostrar_preview_importacion_chatgpt(ordenes_importadas):
    if not ordenes_importadas:
        st.error("No se detectaron órdenes en el JSON. Revisá que hayas copiado todo el texto completo.")
        return

    st.success(f"Lectura correcta: {len(ordenes_importadas)} orden/es detectada/s.")

    df_preview = pd.DataFrame(ordenes_importadas)
    columnas_preview = [
        "estado", "numero_orden", "cliente", "lote", "nombre_tela", "color_tela",
        "metros_recibidos", "ambiente", "ancho_riel", "alto_terminado",
        "metraje_corte", "apertura", "uso", "motivo_revision"
    ]
    for col in columnas_preview:
        if col not in df_preview.columns:
            df_preview[col] = ""

    st.dataframe(
        df_preview[columnas_preview],
        use_container_width=True,
        hide_index=True
    )


def mostrar_importador_json_chatgpt():
    st.markdown("### 📥 Importar órdenes desde ChatGPT / WhatsApp")
    st.write(
        "Usá esta opción cuando no quieras gastar Gemini/API. Si el celular no deja subir archivos JSON, "
        "copiá el texto del JSON desde WhatsApp y pegalo acá."
    )

    ejemplo = plantilla_json_chatgpt()
    st.download_button(
        "⬇️ Descargar modelo de JSON para ChatGPT",
        data=json.dumps(ejemplo, ensure_ascii=False, indent=4),
        file_name="modelo_ordenes_chatgpt.json",
        mime="application/json",
        key="descargar_modelo_json_chatgpt"
    )

    tab_pegar, tab_archivo = st.tabs(["📋 Pegar JSON desde WhatsApp", "📁 Subir archivo JSON/TXT"])

    with tab_pegar:
        st.markdown("""
        <div class="info-box">
            📱 <b>Recomendado para celular y WhatsApp:</b><br>
            1. Copiá el mensaje JSON completo que te mandé por WhatsApp o ChatGPT.<br>
            2. Pegalo en el cuadro de abajo.<br>
            3. Tocá <b>Leer texto pegado</b>.<br>
            4. Revisá y agregá a la bandeja.
        </div>
        """, unsafe_allow_html=True)

        texto_json = st.text_area(
            "Pegá acá el JSON completo",
            value=st.session_state.get("texto_json_pegado_chatgpt", ""),
            height=260,
            key="texto_json_pegado_chatgpt"
        )

        if st.button("📋 Leer texto pegado", type="primary", key="btn_leer_texto_json_chatgpt"):
            try:
                payload = extraer_payload_json_desde_texto(texto_json)
                ordenes_importadas = normalizar_payload_importado(payload, "texto_pegado_whatsapp_chatgpt")
                st.session_state.ordenes_importadas_chatgpt_tmp = ordenes_importadas
                st.session_state.origen_importacion_chatgpt_tmp = "texto pegado"
            except Exception as e:
                st.session_state.ordenes_importadas_chatgpt_tmp = []
                st.error(f"No se pudo leer el texto pegado: {e}")

    with tab_archivo:
        st.info("Esta opción funciona bien en PC. En algunos celulares Android el selector no deja tomar archivos .json; en ese caso usá la pestaña de pegar texto.")
        archivo_json = st.file_uploader(
            "Subir archivo generado por ChatGPT (.json o .txt)",
            type=["json", "txt"],
            key="uploader_json_chatgpt"
        )

        if archivo_json and st.button("📁 Leer archivo", type="primary", key="btn_leer_archivo_json_chatgpt"):
            try:
                payload = leer_json_subido(archivo_json)
                ordenes_importadas = normalizar_payload_importado(payload, archivo_json.name)
                st.session_state.ordenes_importadas_chatgpt_tmp = ordenes_importadas
                st.session_state.origen_importacion_chatgpt_tmp = archivo_json.name
            except Exception as e:
                st.session_state.ordenes_importadas_chatgpt_tmp = []
                st.error(f"No se pudo leer el archivo: {e}")

    ordenes_tmp = st.session_state.get("ordenes_importadas_chatgpt_tmp", [])
    if not ordenes_tmp:
        st.info("Cuando leas un JSON, el programa mostrará una vista previa antes de agregarlo a la bandeja. Nada se manda a corte sin confirmar.")
        return

    st.markdown(f"#### Vista previa importada desde: {st.session_state.get('origen_importacion_chatgpt_tmp', 'ChatGPT')}")
    mostrar_preview_importacion_chatgpt(ordenes_tmp)

    col_agregar, col_limpiar = st.columns([2, 1])
    with col_agregar:
        if st.button("📥 Agregar a la bandeja de revisión", type="primary", key="btn_agregar_importacion_chatgpt"):
            st.session_state.ordenes_detectadas.extend(ordenes_tmp)
            st.session_state.ordenes_importadas_chatgpt_tmp = []
            st.success("Importación agregada a la bandeja. Revisá, corregí si hace falta y confirmá las filas tildadas.")
            st.rerun()
    with col_limpiar:
        if st.button("🧹 Limpiar importación", key="btn_limpiar_importacion_chatgpt"):
            st.session_state.ordenes_importadas_chatgpt_tmp = []
            st.rerun()


def mostrar_resumen_bandeja():
    ordenes = st.session_state.get("ordenes_detectadas", [])
    if not ordenes:
        return

    ordenes, resumen = preparar_metros_automaticos_por_lote(ordenes, solo_tildadas=False)
    st.session_state.ordenes_detectadas = ordenes

    pendientes = sum(1 for orden in ordenes if not clave_lote_desde_orden(orden))

    st.markdown("#### 📦 Agrupación detectada por lote/tela")

    if resumen:
        df_resumen = pd.DataFrame(resumen)
        st.dataframe(
            df_resumen[["lote_tela_color", "cortinas", "suma_cortes", "metros_lote", "origen", "aviso"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "lote_tela_color": "Lote / Tela / Color",
                "cortinas": "Cortinas",
                "suma_cortes": st.column_config.NumberColumn("Suma cortes", format="%.2f m"),
                "metros_lote": st.column_config.NumberColumn("Metros que se cargarán al lote", format="%.2f m"),
                "origen": "Origen metros",
                "aviso": "Aviso",
            }
        )

    if pendientes:
        st.warning(
            f"Hay {pendientes} orden/es sin lote claro. No conviene enviarlas a corte hasta corregirlas."
        )

    st.info(
        "Los metros recibidos del lote se completan automáticamente: si la oficina los informa, se toma ese total; "
        "si no aparecen, el sistema los calcula sumando los metrajes/cortes de las órdenes del mismo lote."
    )


def mostrar_scanner_ia_masivo():
    st.markdown("## 📥 Bandeja de órdenes de administración")
    st.markdown(
        "Importá un JSON desde ChatGPT o subí fotos de órdenes MORO. En V7 las fotos se achican/comprimen y se pueden leer en tandas de varias imágenes por consulta. Primero se leen y se revisan; "
        "recién después se cargan en el lote correcto. No hace falta crear el lote ni cargar metros antes: "
        "si la oficina informa el metraje del lote, se toma de la orden; si no aparece, se calcula por suma de cortes."
    )

    with st.expander("📥 Importar JSON desde ChatGPT (sin gastar IA)", expanded=True):
        mostrar_importador_json_chatgpt()

    with st.expander("📸 Escanear órdenes MORO con IA", expanded=False):
        fotos = st.file_uploader(
            "Elegir una o varias imágenes de órdenes",
            type=["jpg", "jpeg", "png"],
            accept_multiple_files=True,
            key="uploader_ordenes_moro"
        )

        c1, c2, c3 = st.columns([1.5, 1.2, 1])

        with c1:
            procesar = st.button("🪄 Leer todas las órdenes", type="primary")
        with c2:
            if st.button("🧹 Vaciar bandeja IA"):
                st.session_state.ordenes_detectadas = []
                st.rerun()
        with c3:
            st.caption("No se carga nada al taller hasta confirmar.")

        if fotos:
            st.caption(
                f"V7 optimiza las fotos antes de enviarlas: máximo {MAX_LADO_IMAGEN_IA}px, "
                f"calidad JPG {CALIDAD_JPEG_IA}. También lee varias fotos por consulta para gastar menos llamadas."
            )

            tam_lote = st.selectbox(
                "Fotos por consulta a Gemini",
                [1, 2, 3, 4, 5],
                index=4,
                help="Con 5 fotos por consulta, 10 fotos usan aproximadamente 2 llamadas en vez de 10. Si una tanda falla, bajá a 2 o 3."
            )
            llamadas_estimadas = (len(fotos) + int(tam_lote) - 1) // int(tam_lote)
            st.info(
                f"Fotos cargadas: {len(fotos)} | Tanda: {tam_lote} foto/s | "
                f"Llamadas estimadas a Gemini: {llamadas_estimadas}."
            )

        if procesar:
            if not fotos:
                st.warning("Primero subí una o varias fotos de órdenes.")
            else:
                nuevas = []
                imagenes_optimizadas = []
                detalles_optimizacion = []
                barra = st.progress(0)
                total = len(fotos)

                for idx, foto in enumerate(fotos, start=1):
                    try:
                        img_opt, info_opt = optimizar_imagen_para_ia(foto)
                        imagenes_optimizadas.append((img_opt, foto.name))
                        detalles_optimizacion.append(info_opt)
                    except Exception as e:
                        st.error(f"No se pudo optimizar/abrir {foto.name}: {e}")
                        nuevas.append(normalizar_orden_detectada({"observaciones": f"Error imagen: {e}"}, foto.name))
                    barra.progress(idx / max(total, 1))

                if detalles_optimizacion:
                    with st.expander("📉 Ver optimización de fotos", expanded=False):
                        st.dataframe(pd.DataFrame(detalles_optimizacion), use_container_width=True)

                tam_lote_seguro = int(locals().get("tam_lote", TAMANIO_LOTE_IA_DEFAULT))
                total_tandas = (len(imagenes_optimizadas) + tam_lote_seguro - 1) // tam_lote_seguro if imagenes_optimizadas else 0
                barra_ia = st.progress(0)

                for nro_tanda, inicio in enumerate(range(0, len(imagenes_optimizadas), tam_lote_seguro), start=1):
                    tanda = imagenes_optimizadas[inicio:inicio + tam_lote_seguro]
                    nombres = ", ".join(nombre for _, nombre in tanda)
                    with st.spinner(f"Leyendo tanda {nro_tanda} de {total_tandas}: {nombres}"):
                        nuevas.extend(analizar_ordenes_lote_con_ia(tanda))
                    barra_ia.progress(nro_tanda / max(total_tandas, 1))

                st.session_state.ordenes_detectadas.extend(nuevas)
                st.success(
                    f"Se procesaron {len(nuevas)} orden/es. "
                    "Revisá la tabla antes de cargar. Si alguna tanda figura REVISAR, corregila manualmente sin volver a gastar IA."
                )

        if st.session_state.ordenes_detectadas:
            st.session_state.ordenes_detectadas, _ = preparar_metros_automaticos_por_lote(
                st.session_state.ordenes_detectadas,
                solo_tildadas=False
            )
            st.markdown("### ✅ Revisión antes de cargar")
            st.info(
                "Revisá especialmente LOTE / TELA / COLOR. Si el lote está mal, el fruncido y el sobrante quedan mal. "
                "Podés corregir cualquier celda antes de confirmar."
            )

            df = pd.DataFrame(st.session_state.ordenes_detectadas)
            columnas = [
                "cargar", "estado", "archivo", "numero_orden", "cliente", "telefono",
                "lote", "nombre_tela", "color_tela", "metros_recibidos", "origen_metros", "ambiente",
                "ancho_riel", "alto_terminado", "metraje_corte", "apertura", "uso",
                "observaciones", "motivo_revision"
            ]
            for col in columnas:
                if col not in df.columns:
                    df[col] = ""
            df = df[columnas]

            editado = st.data_editor(
                df,
                use_container_width=True,
                num_rows="dynamic",
                hide_index=True,
                column_config={
                    "cargar": st.column_config.CheckboxColumn("Cargar", help="Tildar solo cuando la fila esté revisada."),
                    "estado": st.column_config.TextColumn("Estado", disabled=True),
                    "archivo": st.column_config.TextColumn("Archivo", disabled=True),
                    "apertura": st.column_config.SelectboxColumn("Apertura", options=APERTURAS),
                    "uso": st.column_config.SelectboxColumn("Trabajo", options=TIPOS_TRABAJO),
                    "ancho_riel": st.column_config.NumberColumn("Ancho riel", step=0.01, format="%.2f"),
                    "alto_terminado": st.column_config.NumberColumn("Alto terminado", step=0.01, format="%.2f"),
                    "metraje_corte": st.column_config.NumberColumn("Metraje/corte", step=0.01, format="%.2f"),
                    "metros_recibidos": st.column_config.NumberColumn("Metros lote", step=0.10, format="%.2f"),
                    "origen_metros": st.column_config.TextColumn("Origen metros", disabled=True),
                },
                key="editor_bandeja_ia"
            )

            ordenes_editadas = dataframe_a_ordenes(editado)
            st.session_state.ordenes_detectadas = ordenes_editadas
            mostrar_resumen_bandeja()

            st.download_button(
                "⬇️ Descargar bandeja IA en JSON",
                data=json.dumps(ordenes_editadas, ensure_ascii=False, indent=4),
                file_name="bandeja_ordenes_moro.json",
                mime="application/json"
            )

            if st.button("✅ Confirmar y cargar órdenes tildadas en sus lotes", type="primary"):
                ordenes_editadas, resumen_confirmacion = preparar_metros_automaticos_por_lote(ordenes_editadas, solo_tildadas=True)
                cargadas = 0
                omitidas = []

                for orden in ordenes_editadas:
                    if not bool(orden.get("cargar")):
                        continue

                    estado, motivo = evaluar_estado_orden(orden)
                    if estado != "OK":
                        omitidas.append(f"{orden.get('archivo', 'orden')}: {motivo}")
                        continue

                    cargar_orden_como_cortina(orden)
                    cargadas += 1

                    if not st.session_state.data.get("cliente") and orden.get("cliente"):
                        st.session_state.data["cliente"] = texto_seguro(orden.get("cliente"))
                    if not st.session_state.data.get("telefono") and orden.get("telefono"):
                        st.session_state.data["telefono"] = texto_seguro(orden.get("telefono"))

                guardar_backup()

                if cargadas:
                    st.session_state.ordenes_detectadas = [o for o in ordenes_editadas if not bool(o.get("cargar"))]
                    st.success(f"Se cargaron {cargadas} cortina/s en el programa de costura.")
                    if omitidas:
                        st.warning("Algunas filas fueron omitidas porque siguen incompletas:\n" + "\n".join(omitidas[:10]))
                    st.rerun()
                else:
                    st.warning("No se cargó ninguna orden. Tildá 'Cargar' y verificá que lote, ancho, alto y metraje estén completos.")


# =====================================================
# INTERFAZ
# =====================================================

if st.session_state.get("vista") == "COSTURA_TALLER":
    mostrar_bloque_taller()
else:


    st.markdown(
        '<div class="main-title">🧵 CastaMuebles IA V6 - Gestión Textil Pro</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        '<div class="subtitle">Sistema desarrollado por CASTAÑEDA Luciano.</div>',
        unsafe_allow_html=True
    )

    st.markdown("""
    <div class="important-box">
        REGLA DE ORO:<br>
        La solapa no depende de si el trabajo es apaisado o vertical.<br>
        La solapa depende de si hay cruce entre paños.<br><br>
        TABLAS:<br>
        Si la medida visible no es múltiplo de 10 cm, la tabla se ajusta cerca de 10 cm para empezar y terminar en tabla.<br><br>
        ALTURA DE CORTE ACTUAL DEL TALLER:<br>
        Cabezal/superior <b>16 cm</b> + ruedo/inferior <b>5 cm</b> = <b>21 cm</b> sobre el alto terminado.
    </div>
    """, unsafe_allow_html=True)

    mostrar_scanner_ia_masivo()

    st.divider()

    st.markdown("## 🧾 Datos del cliente")

    col_a, col_b, col_c = st.columns(3)

    with col_a:
        st.session_state.data["cliente"] = st.text_input(
            "Cliente",
            value=st.session_state.data.get("cliente", "")
        )

    with col_b:
        st.session_state.data["telefono"] = st.text_input(
            "Teléfono",
            value=st.session_state.data.get("telefono", "")
        )

    with col_c:
        st.session_state.data["fecha"] = st.text_input(
            "Fecha",
            value=st.session_state.data.get("fecha", str(date.today()))
        )

    st.session_state.data["observaciones"] = st.text_area(
        "Observaciones generales",
        value=st.session_state.data.get("observaciones", "")
    )

    guardar_backup()

    st.divider()

    col_btn1, col_btn2 = st.columns([1, 4])

    with col_btn1:
        if st.button("➕ Agregar tela / lote"):
            st.session_state.data["telas"].append({
                "nombre": f"Tela {len(st.session_state.data['telas']) + 1}",
                "color": "",
                "metros_recibidos": 0.0,
                "fruncido_deseado": 2.2,
                "solapa_cm": SOLAPA_DEFAULT_CM,
                "cortinas": []
            })

            guardar_backup()
            st.rerun()

    with col_btn2:
        if st.button("🗑️ Borrar toda la orden"):
            resetear_todo()


    if not st.session_state.data["telas"]:
        st.info("Agregá una tela/lote para carga manual, o usá la Bandeja IA: ahí el lote y los metros se completan desde las órdenes de administración.")
    else:
        for i, tela in enumerate(st.session_state.data["telas"]):
            st.markdown(f"## 📦 Tela / Lote {i + 1}")

            c1, c2, c3, c4 = st.columns(4)

            with c1:
                tela["nombre"] = st.text_input(
                    "Nombre tela",
                    value=tela.get("nombre", ""),
                    key=f"nombre_tela_{i}"
                )

            with c2:
                tela["color"] = st.text_input(
                    "Color",
                    value=tela.get("color", ""),
                    key=f"color_tela_{i}"
                )

            with c3:
                tela["metros_recibidos"] = st.number_input(
                    "Metros recibidos del lote (auto desde oficina o manual)",
                    value=float(tela.get("metros_recibidos", 0.0)),
                    step=0.10,
                    key=f"metros_tela_{i}"
                )

            with c4:
                tela["fruncido_deseado"] = st.number_input(
                    "Fruncido deseado",
                    value=float(tela.get("fruncido_deseado", 2.2)),
                    step=0.10,
                    key=f"fruncido_tela_{i}"
                )

            x1, x2 = st.columns(2)

            with x1:
                tela["solapa_cm"] = st.number_input(
                    "Solapa / cruce cm",
                    value=int(tela.get("solapa_cm", SOLAPA_DEFAULT_CM)),
                    step=1,
                    key=f"solapa_tela_{i}"
                )

            with x2:
                if st.button("➕ Agregar cortina", key=f"agregar_cortina_{i}"):
                    tela["cortinas"].append({
                        "ambiente": f"Cortina {len(tela['cortinas']) + 1}",
                        "ancho_riel": 2.40,
                        "alto_terminado": 2.51,
                        "tipo_trabajo": "Vertical",
                        "apertura": "Central",
                        "cabezal_cm": CABEZAL_DEFAULT_CM,
                        "ruedo_cm": RUEDO_DEFAULT_CM,
                        "metraje_asignado": 0.0,
                        "ancho_pano_izq": 1.20,
                        "ancho_pano_der": 1.20,
                        "hay_cruce": True,
                        "pano_solapa": "Derecha"
                    })

                    guardar_backup()
                    st.rerun()

            st.markdown("### 🪟 Cortinas")

            for j, cortina in enumerate(tela["cortinas"]):
                normalizar_cortina(cortina)

                nombre_cortina_header = cortina.get("ambiente", "Cortina") or "Cortina"
                ancho_header = float(cortina.get("ancho_riel", 0.0))
                alto_header = float(cortina.get("alto_terminado", 0.0))

                cab1, cab2 = st.columns([3, 1.45])
                with cab1:
                    st.markdown(
                        f"""
                        <div class="cortina-header-card">
                            <div class="cortina-header-title">🪟 {nombre_cortina_header}</div>
                            <div class="cortina-header-subtitle">
                                Ancho: {ancho_header:.2f} m | Alto: {alto_header:.2f} m | Esta es la cortina seleccionada
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                with cab2:
                    st.write("")
                    if st.button(
                        f"🧵 FABRICAR {nombre_cortina_header.upper()}",
                        key=f"fabricar_taller_top_{i}_{j}",
                        type="primary",
                        use_container_width=True
                    ):
                        st.session_state.tela_seleccionada = i
                        st.session_state.cortina_seleccionada = j
                        st.session_state.vista = "COSTURA_TALLER"
                        st.rerun()

                with st.expander(
                    f"✏️ Editar medidas de {nombre_cortina_header}",
                    expanded=True
                ):
                    a1, a2, a3, a4 = st.columns(4)

                    with a1:
                        cortina["ambiente"] = st.text_input(
                            "Ambiente",
                            value=cortina.get("ambiente", ""),
                            key=f"ambiente_{i}_{j}"
                        )

                        cortina["ancho_riel"] = st.number_input(
                            "Ancho riel",
                            value=float(cortina.get("ancho_riel", 2.40)),
                            step=0.01,
                            key=f"ancho_{i}_{j}"
                        )

                    with a2:
                        cortina["alto_terminado"] = st.number_input(
                            "Alto terminado",
                            value=float(cortina.get("alto_terminado", 2.51)),
                            step=0.01,
                            key=f"alto_{i}_{j}"
                        )

                        cortina["tipo_trabajo"] = st.selectbox(
                            "Trabajo",
                            TIPOS_TRABAJO,
                            index=TIPOS_TRABAJO.index(
                                cortina.get("tipo_trabajo", "Vertical")
                            ),
                            key=f"tipo_{i}_{j}"
                        )

                    with a3:
                        cortina["apertura"] = st.selectbox(
                            "Apertura",
                            APERTURAS,
                            index=APERTURAS.index(
                                cortina.get("apertura", "Central")
                            ),
                            key=f"apertura_{i}_{j}"
                        )

                        cortina["cabezal_cm"] = st.number_input(
                            "Cabezal",
                            value=int(cortina.get("cabezal_cm", CABEZAL_DEFAULT_CM)),
                            step=1,
                            key=f"cabezal_{i}_{j}"
                        )

                    with a4:
                        cortina["ruedo_cm"] = st.number_input(
                            "Ruedo",
                            value=int(cortina.get("ruedo_cm", RUEDO_DEFAULT_CM)),
                            step=1,
                            key=f"ruedo_{i}_{j}"
                        )

                        metraje_sugerido = calcular_metraje_cortina(
                            cortina,
                            tela["solapa_cm"],
                            tela["fruncido_deseado"]
                        )

                        if float(cortina.get("metraje_asignado", 0.0)) <= 0:
                            cortina["metraje_asignado"] = round(metraje_sugerido, 2)

                        cortina["metraje_asignado"] = st.number_input(
                            "Metraje asignado",
                            value=float(cortina["metraje_asignado"]),
                            step=0.01,
                            key=f"metraje_{i}_{j}"
                        )

                    if cortina["apertura"] == "Central":
                        st.markdown("#### ⚖️ Distribución de paños")

                        p1, p2, p3, p4 = st.columns(4)

                        with p1:
                            cortina["ancho_pano_izq"] = st.number_input(
                                "Paño izquierdo",
                                value=float(cortina["ancho_pano_izq"]),
                                step=0.01,
                                key=f"izq_{i}_{j}"
                            )

                        with p2:
                            cortina["ancho_pano_der"] = st.number_input(
                                "Paño derecho",
                                value=float(cortina["ancho_pano_der"]),
                                step=0.01,
                                key=f"der_{i}_{j}"
                            )

                        with p3:
                            cortina["hay_cruce"] = st.checkbox(
                                "Hay cruce",
                                value=bool(cortina["hay_cruce"]),
                                key=f"cruce_{i}_{j}"
                            )

                        with p4:
                            if cortina["hay_cruce"]:
                                cortina["pano_solapa"] = st.selectbox(
                                    "Paño con solapa",
                                    PANOS_SOLAPA,
                                    index=0 if cortina["pano_solapa"] == "Izquierda" else 1,
                                    key=f"solapa_pano_{i}_{j}"
                                )
                            else:
                                st.info("Sin cruce: no se aplica solapa.")

                    else:
                        cortina["hay_cruce"] = False

                    st.markdown("---")
                    st.caption("El botón para enviar a taller está arriba, pegado al nombre de esta cortina, para evitar confusiones.")

                    control_rapido_cortina(cortina, tela)

                    if st.button(
                        "🗑️ Eliminar cortina",
                        key=f"eliminar_{i}_{j}"
                    ):
                        tela["cortinas"].pop(j)
                        guardar_backup()
                        st.rerun()

                    guardar_backup()

            st.divider()


    # =====================================================
    # RESUMEN GENERAL
    # =====================================================

    st.markdown("## 📊 Resumen general por tela")

    if not st.session_state.data["telas"]:
        st.info("No hay telas cargadas.")
    else:
        for i, tela in enumerate(st.session_state.data["telas"]):
            nombre_tela = tela.get("nombre", f"Tela {i + 1}")
            color_tela = tela.get("color", "")

            metros_recibidos = float(tela.get("metros_recibidos", 0.0))
            fruncido_deseado = float(tela.get("fruncido_deseado", 2.2))

            total_teorico_fruncido = total_metraje_tela(tela, fruncido_deseado)
            total_asignado = sum(
                float(c.get("metraje_asignado", 0.0))
                for c in tela["cortinas"]
            )
            # Validación principal del lote:
            # La tela que falta/sobra se controla contra los cortes exactos/asignados
            # que vienen de administración o fueron cargados manualmente.
            # La fórmula teórica queda como control técnico, no como sentencia de falta de tela.
            sobrante_asignado = metros_recibidos - total_asignado
            diferencia_teorica = total_asignado - total_teorico_fruncido
            fruncido_max = fruncido_maximo_parejo(tela)

            st.markdown(f"### 📦 {nombre_tela} {f'- {color_tela}' if color_tela else ''}")

            r1, r2, r3, r4 = st.columns(4)

            r1.metric("Metros recibidos", f"{metros_recibidos:.2f} m")
            r2.metric("Corte asignado / administración", f"{total_asignado:.2f} m")
            r3.metric("Sobrante contra cortes", f"{sobrante_asignado:.2f} m")
            r4.metric("Control teórico", f"{total_teorico_fruncido:.2f} m")

            origen_metros_lote = texto_seguro(tela.get("origen_metros"))
            if origen_metros_lote:
                st.caption(f"Origen metros del lote: {origen_metros_lote}")

            if tela.get("lote_id"):
                st.caption(f"Lote identificado: {tela.get('lote_id')}")

            if origen_metros_lote.lower().startswith("calculado"):
                st.info("Metros del lote calculados por suma de cortes importados. Revisar contra la orden de administración antes de cortar.")

            if abs(diferencia_teorica) >= 0.20:
                st.info(
                    f"Control técnico: el corte asignado difiere {diferencia_teorica:+.2f} m del cálculo teórico por fruncido deseado. "
                    "Esto NO declara falta de tela; solo sirve para revisar fruncido, paños o metraje enviado por administración."
                )

            if not tela["cortinas"]:
                st.warning("Esta tela todavía no tiene cortinas cargadas.")
                continue

            if metros_recibidos <= 0:
                st.warning("Cargá los metros recibidos para validar si alcanza.")
            elif sobrante_asignado >= -0.01:
                st.markdown("""
                <div class="ok-box">
                    ✅ La tela alcanza según los cortes exactos/asignados a cada cortina.
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown("""
                <div class="danger-box">
                    ⚠️ La tela NO alcanza contra los cortes exactos/asignados. Revisar lote, metros recibidos y órdenes agrupadas antes de cortar.
                </div>
                """, unsafe_allow_html=True)

            datos_lote = calcular_pico_maestro_lote(tela)
            pico_maestro = datos_lote.get("pico_maestro_cm")

            st.info(f"Fruncido máximo parejo posible para todo este lote: {fruncido_max:.2f}")

            if pico_maestro is not None:
                st.info(
                    f"Pico maestro del lote: {pico_maestro:.2f} cm | "
                    f"Estructura rígida total: {datos_lote['estructura_total']:.2f} m | "
                    f"Picos totales: {datos_lote['picos_totales']}"
                )

                if pico_maestro <= 5:
                    st.warning(
                        "⚠️ Pico maestro bajo. Esto no significa necesariamente que falte tela; "
                        "significa que, con los metros cargados para este lote, el pico/fruncido puede quedar pobre. "
                        "Revisar lote, metraje recibido y cortes antes de fabricar."
                    )


    # =====================================================
    # RESPALDO
    # =====================================================

    st.markdown("## 💾 Respaldo")

    guardar_backup()

    if ARCHIVO_BACKUP.exists():
        with open(ARCHIVO_BACKUP, "r", encoding="utf-8") as f:
            contenido = f.read()

        st.download_button(
            "⬇️ Descargar respaldo",
            data=contenido,
            file_name="backup_castamuebles_pro.json",
            mime="application/json"
        )

    st.caption("Sistema local/offline.")

    # =====================================================
    # MI ELECCIÓN PARA TU QUINCHO
    # =====================================================

    st.divider()
    st.markdown("## 🏡 Mi elección para tu quincho")
    st.markdown("""
    <div style="
        background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%);
        border: 2px solid #16a34a;
        border-radius: 18px;
        padding: 22px 26px;
        margin-top: 10px;
        box-shadow: 0 6px 18px rgba(22, 163, 74, 0.12);
    ">
        <div style="font-size: 22px; font-weight: 900; color: #14532d; margin-bottom: 10px;">
            🪟 Corrediza Módena 2 hojas
        </div>
        <div style="font-size: 16px; color: #166534; font-weight: 700; margin-bottom: 14px; line-height: 1.6;">
            ✅ DVH 4+9+4 &nbsp;|&nbsp; ✅ Aluminio anodizado &nbsp;|&nbsp; ✅ Protector bajo anti-rasguños
        </div>
        <a href="https://listado.mercadolibre.com.ar/ventanas-aluminio-modena-anodizado-dvh"
           target="_blank"
           style="
               display: inline-block;
               background: #16a34a;
               color: white;
               font-size: 17px;
               font-weight: 900;
               padding: 12px 28px;
               border-radius: 12px;
               text-decoration: none;
               box-shadow: 0 4px 12px rgba(22, 163, 74, 0.3);
           ">
            🛒 Ver en Mercado Libre
        </a>
    </div>
    """, unsafe_allow_html=True)
