import streamlit as st
import streamlit.components.v1 as components
import json
import google.generativeai as genai
from pathlib import Path
from datetime import date
from textwrap import dedent
from PIL import Image

# =====================================================
# CONFIGURACIÓN DE IA (GEMINI) - SEGURIDAD CON SECRETS
# =====================================================
# Luciano: Ya dejé configurado para que el programa busque la llave en 
# los "Secrets" de Streamlit Cloud. No tenés que tocar nada acá.
try:
    API_KEY = st.secrets["GEMINI_KEY"]
    genai.configure(api_key=API_KEY)
except Exception:
    st.warning("⚠️ Falta configurar la GEMINI_KEY en los Secrets de Streamlit.")

def analizar_orden_con_ia(imagen_pil):
    """Envía la foto a Gemini para extraer los datos de MORO."""
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = """
    Analiza esta hoja de producción de cortinas de la empresa MORO. 
    Extrae EXACTAMENTE estos datos y devuélvelos en formato JSON puro:
    - ancho_riel: El valor de 'Ancho de Cortina' (ej: 1.75)
    - alto_terminado: El valor de 'Alto terminado' (ej: 2.47)
    - metraje_corte: El valor de 'Corte exacto de paño x ancho' del punto 3 (ej: 3.85)
    - apertura: Si dice 'Derecha', 'Izquierda' o 'Central'.
    - uso: Si dice 'Apaisado' o 'Vertical'.
    - ambiente: El nombre que aparece después de 'Cortina 1:' (ej: DOMITORIO 1).
    
    Responde solo el JSON sin etiquetas markdown.
    """
    try:
        response = model.generate_content([prompt, imagen_pil])
        limpio = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(limpio)
    except Exception as e:
        st.error(f"Error al leer la imagen: {e}")
        return None

# =====================================================
# CONFIGURACIÓN DE PÁGINA Y ESTILOS
# =====================================================
st.set_page_config(page_title="CastaMuebles Pro - Escáner IA", page_icon="🧵", layout="wide")

ARCHIVO_BACKUP = Path("backup_castamuebles_pro.json")

# --- Lógica de Estado ---
if "data" not in st.session_state:
    if ARCHIVO_BACKUP.exists():
        with open(ARCHIVO_BACKUP, "r", encoding="utf-8") as f:
            st.session_state.data = json.load(f)
    else:
        st.session_state.data = {"cliente": "", "telefono": "", "fecha": str(date.today()), "telas": []}

def guardar():
    with open(ARCHIVO_BACKUP, "w", encoding="utf-8") as f:
        json.dump(st.session_state.data, f, ensure_ascii=False, indent=4)

# =====================================================
# INTERFAZ PRINCIPAL
# =====================================================

st.markdown("""
<style>
    .main-title { font-size: 34px; font-weight: 800; color: #1e293b; }
    .ia-panel { 
        background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%);
        border: 2px solid #0ea5e9;
        padding: 25px;
        border-radius: 20px;
        margin-bottom: 30px;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">🧵 CastaMuebles Pro</div>', unsafe_allow_html=True)
st.caption(f"Desarrollado para Luciano Castañeda | {date.today()}")

# PANEL DE IA
with st.container():
    st.markdown('<div class="ia-panel">', unsafe_allow_html=True)
    st.markdown("### 📸 Escáner de Órdenes de Producción")
    st.write("Subí la foto de la hoja de MORO para cargar los datos automáticamente.")
    
    foto = st.file_uploader("Elegir imagen...", type=["jpg", "png", "jpeg"])
    
    if foto:
        if st.button("🪄 PROCESAR Y CARGAR CORTINA"):
            img = Image.open(foto)
            with st.spinner("La IA está analizando la hoja de MORO..."):
                res = analizar_orden_con_ia(img)
                if res:
                    if not st.session_state.data["telas"]:
                        st.session_state.data["telas"].append({
                            "nombre": "Lote Principal", "color": "-", 
                            "metros_recibidos": 0.0, "fruncido_deseado": 2.2, 
                            "solapa_cm": 10, "cortinas": []
                        })
                    
                    # Carga automática de los datos detectados
                    nueva_cortina = {
                        "ambiente": res.get("ambiente", "Nueva Cortina"),
                        "ancho_riel": float(res.get("ancho_riel", 0)),
                        "alto_terminado": float(res.get("alto_terminado", 0)),
                        "tipo_trabajo": res.get("uso", "Apaisado"),
                        "apertura": res.get("apertura", "Derecha"),
                        "cabezal_cm": 22, "ruedo_cm": 5,
                        "metraje_asignado": float(res.get("metraje_corte", 0)),
                        "ancho_pano_izq": float(res.get("ancho_riel", 0)),
                        "ancho_pano_der": 0.0,
                        "hay_cruce": False, "pano_solapa": "Derecha"
                    }
                    st.session_state.data["telas"][0]["cortinas"].append(nueva_cortina)
                    guardar()
                    st.success(f"✅ ¡{nueva_cortina['ambiente']} cargada correctamente!")
                    st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# Resto de la carga manual (Opcional)
st.markdown("### 📋 Datos Generales")
col1, col2 = st.columns(2)
st.session_state.data["cliente"] = col1.text_input("Cliente", st.session_state.data["cliente"])
st.session_state.data["telefono"] = col2.text_input("Teléfono", st.session_state.data["telefono"])
