import streamlit as st
import streamlit.components.v1 as components
import json
import os
import re
from pathlib import Path
from datetime import date
from textwrap import dedent

import pandas as pd
from PIL import Image

try:
    import google.generativeai as genai
except Exception:
    genai = None

# =====================================================
# CONFIGURACIÓN GENERAL
# =====================================================

st.set_page_config(
    page_title="CastaMuebles IA - Gestión Textil Pro",
    page_icon="🧵",
    layout="wide"
)

ARCHIVO_BACKUP = Path("backup_castamuebles_pro.json")

DOBLADILLO_LATERAL_CM = 4
DOBLADILLO_TOTAL_M = 0.08
SOLAPA_DEFAULT_CM = 10
CABEZAL_DEFAULT_CM = 22
RUEDO_DEFAULT_CM = 5
SEPARACION_TABLAS_CM = 10

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
    tablas = round((medida_visible_m * 100) / SEPARACION_TABLAS_CM)

    if tablas < 2:
        tablas = 2

    picos = tablas - 1
    return tablas, picos


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
            "picos": picos_izq
        })

        panos.append({
            "lado": "Derecha",
            "visible": visible_der,
            "trabajo": visible_der + DOBLADILLO_TOTAL_M,
            "tablas": tablas_der,
            "picos": picos_der
        })

    else:
        visible = ancho_riel
        tablas, picos = tablas_y_picos(visible)

        panos.append({
            "lado": apertura,
            "visible": visible,
            "trabajo": visible + DOBLADILLO_TOTAL_M,
            "tablas": tablas,
            "picos": picos
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
    apertura = cortina.get("apertura", "Central")
    hay_cruce = cortina.get("hay_cruce", apertura == "Central")
    ancho_riel = float(cortina.get("ancho_riel", 0.0))

    solapa_m = (solapa_cm / 100) if hay_solapa_real(apertura, hay_cruce) else 0
    return ancho_riel + solapa_m + DOBLADILLO_TOTAL_M


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
    return tela["metros_recibidos"] / base


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

    if pico_maestro_cm is not None:
        pico_izq = pico_maestro_cm
        pico_der = pico_maestro_cm
        corte_izq = trabajo_izq + ((pico_maestro_cm * picos_izq) / 100)
        corte_der = trabajo_der + ((pico_maestro_cm * picos_der) / 100)
        total_corte_calculado = corte_izq + corte_der
        fruncido_real = total_corte_calculado / base_total if base_total > 0 else 0
    else:
        if base_total <= 0:
            fruncido_real = 0
            corte_izq = 0
            corte_der = 0
        else:
            fruncido_real = metraje_asignado / base_total
            corte_izq = trabajo_izq * fruncido_real
            corte_der = trabajo_der * fruncido_real

        excedente_izq = corte_izq - trabajo_izq
        excedente_der = corte_der - trabajo_der

        pico_izq = (excedente_izq * 100) / picos_izq if picos_izq > 0 else 0
        pico_der = (excedente_der * 100) / picos_der if picos_der > 0 else 0

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
            Separación tabla a tabla: <b>{res['separacion_cm']} cm</b><br>
            Profundidad de cada pico / pinza: <b>{res['pico']:.2f} cm</b><br>
            Fruncido real: <b>{res['fruncido_real']:.2f}</b>
        </div>

        <div class="costurero-alerta">
            ⚠️ El dobladillo NO suma tablas. La primera y última tabla ya lo absorben.
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
            Separación tabla a tabla: <b>{separacion} cm</b><br>
            Profundidad de cada pico / pinza: <b>{pico:.2f} cm</b><br>
            Fruncido real: <b>{fruncido:.2f}</b>
        </div>

        <div class="costurero-alerta">
            ⚠️ No agregar tablas por dobladillo. La solapa cuenta solo si hay cruce.
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
        1. La separación de tablas es fija: <b>{SEPARACION_TABLAS_CM} cm</b>.<br>
        2. La cortina debe empezar en tabla y terminar en tabla.<br>
        3. El dobladillo lateral de {DOBLADILLO_LATERAL_CM} cm por lado NO agrega tablas.<br>
        4. La primera y la última tabla ya incluyen el dobladillo.<br>
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
            Total picos / pinzas: <b>{res['total_picos']}</b> |
            Separación fija: <b>{res['separacion_cm']} cm</b><br>
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
                res["separacion_cm"],
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
                res["separacion_cm"],
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


def bloque_medidas_pano(nombre, corte, tecnico, visible, tablas, picos, profundidad_pico, lleva_solapa):
    tarjetas = [
        ("Corte", formato_m_cm(corte)),
        ("Ancho técnico", formato_m_cm(tecnico)),
        ("Medida visible", formato_m_cm(visible)),
        ("Tablas", f"{tablas}"),
        ("Picos", f"{picos}"),
        ("Profundidad del pico", f"{profundidad_pico:.2f} cm"),
        ("Solapa", lleva_solapa),
    ]
    bloque_tarjetas(f"📏 Medidas de trabajo - {nombre}", tarjetas, "taller-medidas-grid")


def bloque_pasos_pano(nombre, corte, tecnico, visible, profundidad_pico):
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
            f"Entablar con tablas de {SEPARACION_TABLAS_CM} cm y picos de {profundidad_pico:.2f} cm de profundidad.",
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
                lleva_solapa
            )
            bloque_pasos_pano(
                "Paño izquierdo",
                res["corte_izq"],
                res["trabajo_izq"],
                res["visible_izq"],
                res["pico_izq"]
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
                lleva_solapa
            )
            bloque_pasos_pano(
                "Paño derecho",
                res["corte_der"],
                res["trabajo_der"],
                res["visible_der"],
                res["pico_der"]
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
            solapa_real_texto
        )
        bloque_pasos_pano(
            "Paño único",
            res["corte_total"],
            res["trabajo"],
            res["visible"],
            res["pico"]
        )



# =====================================================
# BLOQUE 0 - ESCÁNER IA MASIVO DE ÓRDENES MORO
# =====================================================

MODELO_GEMINI = "gemini-2.5-flash"


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
    """Extrae JSON aunque Gemini lo devuelva entre ```json ... ``` o con texto alrededor."""
    if texto is None:
        return {}

    limpio = str(texto).strip()
    limpio = limpio.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(limpio)
    except Exception:
        pass

    match = re.search(r"\{.*\}", limpio, flags=re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
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
    lote = texto_seguro(orden.get("lote"))
    tela = texto_seguro(orden.get("nombre_tela"))
    color = texto_seguro(orden.get("color_tela"))

    partes = [p for p in [lote, tela, color] if p]
    if not partes:
        return ""

    return " | ".join(partes)


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


def analizar_orden_con_ia(imagen_pil, nombre_archivo="orden"):
    """Envía una orden MORO a Gemini y devuelve una fila normalizada para la bandeja."""
    if not configurar_gemini():
        return None

    model = genai.GenerativeModel(MODELO_GEMINI)
    prompt = """
    Analizá esta imagen de una orden/hoja de producción de cortinas de la empresa MORO.

    Tu tarea es extraer datos para un sistema de corte y armado de cortinas.
    Respondé SOLO un JSON puro, sin markdown, sin explicación y sin texto adicional.

    Usá estas claves exactas:
    {
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
      "metraje_corte": "valor de Corte exacto de paño x ancho / corte asignado, solo número en metros",
      "apertura": "Central, Derecha, Izquierda o Lateral según figure",
      "uso": "Apaisado o Vertical según figure",
      "observaciones": "aclaraciones útiles visibles; si no hay, null"
    }

    Reglas:
    - Si un dato no se ve con claridad, poné null.
    - No inventes lote, tela ni color.
    - No conviertas centímetros si el dato principal está en metros; devolvé metros como número.
    - Si aparecen comas decimales, podés devolver número con punto decimal.
    - No confundas metraje_corte con metros_recibidos:
      * metraje_corte = corte asignado a una cortina/paño/trabajo puntual.
      * metros_recibidos = total de metros que administración envía para todo el lote/tela.
    - Si la orden no muestra metros totales del lote, dejá metros_recibidos en null; el sistema lo calculará por suma de cortes al agrupar.
    """

    try:
        response = model.generate_content([prompt, imagen_pil])
        raw = extraer_json_desde_texto(getattr(response, "text", ""))
        return normalizar_orden_detectada(raw, nombre_archivo)
    except Exception as e:
        st.error(f"Error al leer {nombre_archivo}: {e}")
        return normalizar_orden_detectada({"observaciones": f"Error IA: {e}"}, nombre_archivo)


def encontrar_o_crear_lote(orden):
    data = st.session_state.data
    data.setdefault("telas", [])

    lote_txt = texto_seguro(orden.get("lote"))
    nombre_tela = texto_seguro(orden.get("nombre_tela"))
    color_tela = texto_seguro(orden.get("color_tela"))
    metros = numero_seguro(orden.get("metros_recibidos"), 0.0)

    nombre_lote = nombre_tela or lote_txt or "Lote importado"
    color_lote = color_tela

    def norm(x):
        return texto_seguro(x).lower().strip()

    for tela in data["telas"]:
        mismo_nombre = norm(tela.get("nombre")) == norm(nombre_lote)
        mismo_color = not color_lote or norm(tela.get("color")) == norm(color_lote)
        mismo_lote = lote_txt and norm(lote_txt) in norm(tela.get("nombre"))

        if (mismo_nombre and mismo_color) or mismo_lote:
            if metros > 0:
                metros_actuales = float(tela.get("metros_recibidos", 0.0))
                # La bandeja IA trabaja con el metraje de oficina como fuente principal.
                # Si el lote ya existía pero estaba en cero, o si venimos de una confirmación
                # de bandeja, actualizamos el metraje del lote para evitar cortes con fruncido falso.
                if metros_actuales <= 0 or bool(orden.get("_actualizar_metros_lote")):
                    tela["metros_recibidos"] = metros
                    tela["origen_metros"] = texto_seguro(orden.get("origen_metros"), "Oficina / IA")
            if not tela.get("color") and color_lote:
                tela["color"] = color_lote
            tela.setdefault("cortinas", [])
            return tela

    nuevo = {
        "nombre": nombre_lote if not lote_txt else f"{nombre_lote} - Lote {lote_txt}",
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
    Completa metros_recibidos por lote.

    Prioridad:
    1) Si administración/IA leyó metros_recibidos del lote, usa ese total.
    2) Si no hay total de lote, calcula metros_recibidos como suma de metraje_corte
       de las cortinas del mismo lote/tela/color.

    Esto evita pedir el metraje manualmente antes de ver los lotes.
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
        valores_oficina = sorted({
            round(numero_seguro(o.get("metros_recibidos"), 0.0), 2)
            for o in filas
            if numero_seguro(o.get("metros_recibidos"), 0.0) > 0
            and not texto_seguro(o.get("origen_metros")).lower().startswith("calculado")
        })

        if valores_oficina:
            # Si se repite el mismo total en varias órdenes del lote, no se suma varias veces.
            # Si hay valores diferentes, usamos el mayor y lo avisamos en el resumen.
            metros_lote = max(valores_oficina)
            origen = "Oficina"
            aviso = "" if len(valores_oficina) == 1 else f"Valores distintos detectados: {valores_oficina}. Se usó el mayor."
        else:
            metros_lote = suma_cortes
            origen = "Calculado por suma de cortes"
            aviso = "No se detectó total de lote; se sumaron los cortes de las órdenes del mismo lote."

        for orden in filas:
            if numero_seguro(orden.get("metros_recibidos"), 0.0) <= 0 or solo_tildadas:
                orden["metros_recibidos"] = metros_lote
                orden["origen_metros"] = origen
            orden["_actualizar_metros_lote"] = solo_tildadas

        resumen.append({
            "lote_tela_color": clave,
            "cortinas": len(filas),
            "suma_cortes": suma_cortes,
            "metros_lote": metros_lote,
            "origen": origen,
            "aviso": aviso,
        })

    return ordenes, resumen


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
    st.markdown("## 📥 Bandeja IA de órdenes de administración")
    st.markdown(
        "Subí una o varias fotos de órdenes MORO. Primero se leen y se revisan; "
        "recién después se cargan en el lote correcto. No hace falta crear el lote ni cargar metros antes: "
        "si la oficina informa el metraje del lote, se toma de la orden; si no aparece, se calcula por suma de cortes."
    )

    with st.expander("📸 Escanear órdenes MORO con IA", expanded=True):
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

        if procesar:
            if not fotos:
                st.warning("Primero subí una o varias fotos de órdenes.")
            else:
                nuevas = []
                barra = st.progress(0)
                total = len(fotos)
                for idx, foto in enumerate(fotos, start=1):
                    with st.spinner(f"Leyendo orden {idx} de {total}: {foto.name}"):
                        try:
                            img = Image.open(foto).convert("RGB")
                            orden = analizar_orden_con_ia(img, foto.name)
                            if orden:
                                nuevas.append(orden)
                        except Exception as e:
                            st.error(f"No se pudo abrir {foto.name}: {e}")
                            nuevas.append(normalizar_orden_detectada({"observaciones": f"Error imagen: {e}"}, foto.name))
                    barra.progress(idx / total)

                st.session_state.ordenes_detectadas.extend(nuevas)
                st.success(f"Se leyeron {len(nuevas)} orden/es. Revisá la tabla antes de cargar.")

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
        '<div class="main-title">🧵 CastaMuebles IA - Gestión Textil Pro</div>',
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
        La solapa depende de si hay cruce entre paños.
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

                with st.expander(
                    f"🪟 {cortina.get('ambiente', 'Cortina')}",
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

                    if st.button(
                        "🧵 Fabricar esta cortina / Ir a COSTURA - TALLER",
                        key=f"fabricar_taller_{i}_{j}"
                    ):
                        st.session_state.tela_seleccionada = i
                        st.session_state.cortina_seleccionada = j
                        st.session_state.vista = "COSTURA_TALLER"
                        st.rerun()

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

            total_necesario = total_metraje_tela(tela, fruncido_deseado)
            total_asignado = sum(
                float(c.get("metraje_asignado", 0.0))
                for c in tela["cortinas"]
            )
            sobrante_asignado = metros_recibidos - total_asignado
            fruncido_max = fruncido_maximo_parejo(tela)

            st.markdown(f"### 📦 {nombre_tela} {f'- {color_tela}' if color_tela else ''}")

            r1, r2, r3, r4 = st.columns(4)

            r1.metric("Metros recibidos", f"{metros_recibidos:.2f} m")
            r2.metric("Necesario teórico", f"{total_necesario:.2f} m")
            r3.metric("Total asignado", f"{total_asignado:.2f} m")
            r4.metric("Sobrante real", f"{sobrante_asignado:.2f} m")

            if not tela["cortinas"]:
                st.warning("Esta tela todavía no tiene cortinas cargadas.")
                continue

            if metros_recibidos <= 0:
                st.warning("Cargá los metros recibidos para validar si alcanza.")
            elif sobrante_asignado >= 0:
                st.markdown("""
                <div class="ok-box">
                    ✅ La tela alcanza según el metraje asignado a cada cortina.
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown("""
                <div class="danger-box">
                    ⚠️ La tela NO alcanza. Estás asignando más metros de los recibidos.
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
                        "⚠️ Pico maestro bajo. Para este lote, la tela puede no alcanzar "
                        "para mantener un pico estético."
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
