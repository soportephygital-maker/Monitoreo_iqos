import io
import json
import os
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo
from flask import Flask, Response, jsonify, make_response, request

# Importaciones para exportar archivos PDF de ReportLab
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

app = Flask(__name__)

# =========================================================================
# RUTAS PARA VERSIÓN GRATUITA: Se guardan directamente en la raíz de Render
# =========================================================================
ARCHIVO_COMPUTADORAS = "computadoras_db.json"
ARCHIVO_FALLAS = "historial_fallas_db.json"

# Diccionarios y listas en memoria
computadoras = {}
historial_fallas = []

# --- FUNCIONES DE PERSISTENCIA ---
def cargar_datos_locales():
    """Carga los datos desde los archivos JSON en la raíz de Render"""
    global computadoras, historial_fallas
    if os.path.exists(ARCHIVO_COMPUTADORAS):
        try:
            with open(ARCHIVO_COMPUTADORAS, "r", encoding="utf-8") as f:
                computadoras = json.load(f)
        except Exception:
            computadoras = {}
            
    if os.path.exists(ARCHIVO_FALLAS):
        try:
            with open(ARCHIVO_FALLAS, "r", encoding="utf-8") as f:
                historial_fallas = json.load(f)
        except Exception:
            historial_fallas = []

def guardar_datos_locales():
    """Guarda el estado actual directamente en el almacenamiento de Render Gratis"""
    with open(ARCHIVO_COMPUTADORAS, "w", encoding="utf-8") as f:
        json.dump(computadoras, f, ensure_ascii=False, indent=4)
    with open(ARCHIVO_FALLAS, "w", encoding="utf-8") as f:
        json.dump(historial_fallas, f, ensure_ascii=False, indent=4)

# Inicializar los datos guardados al arrancar la App
cargar_datos_locales()

# Configuración de alertas por correo
EMAIL_USER = os.environ.get("soportephygital@gmail.com")
EMAIL_PASS = os.environ.get("obfl nmnm izhl kndg")
EMAIL_DESTINO = "soportephygital@gmail.com"


def enviar_correo_alerta(id_pc, detalle):
    if not EMAIL_USER or not EMAIL_PASS:
        print("[ALERTA] No se envió correo: Faltan credenciales.")
        return

    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_USER
        msg["To"] = EMAIL_DESTINO
        msg["Subject"] = f"🚨 ALERTA: {id_pc} -> {detalle.upper()}"

        cuerpo = f"El sistema de monitoreo informa que el equipo '{id_pc}' cambió de estado crítico: {detalle}."
        msg.attach(MIMEText(cuerpo, "plain"))

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, EMAIL_DESTINO, msg.as_string())
        server.quit()
        print(f"[CORREO] Alerta enviada para {id_pc} ({detalle})")
    except Exception as e:
        print(f"[CORREO ERROR] No se pudo enviar el correo: {e}")


def verificar_y_actualizar_estados():
    zona_mx = ZoneInfo("America/Mexico_City")
    ahora = datetime.now(zona_mx)
    hubo_cambios = False

    for id_pc, info in computadoras.items():
        try:
            ult_conexion = datetime.strptime(
                info["ultima_conexion"], "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=zona_mx)
            diferencia = (ahora - ult_conexion).total_seconds()
            ahora_str = ahora.strftime("%Y-%m-%d %H:%M:%S")

            # CASO 3: Más de 3 minutos -> DESCONECTADO (Rojo)
            if diferencia > 180:
                if info["status"] != "Desconectado":
                    computadoras[id_pc]["status"] = "Desconectado"
                    hubo_cambios = True

                if not info.get("alerta_3m_enviada", False):
                    historial_fallas.append({"id_pc": id_pc, "fecha_falla": ahora_str, "detalle": "Desconectado (Inactividad > 3m)"})
                    computadoras[id_pc]["alerta_3m_enviada"] = True
                    hubo_cambios = True
                    enviar_correo_alerta(id_pc, "Desconectado (>3 min)")

            # CASO 2: Más de 1 minuto -> REINTENTANDO CONEXIÓN (Naranja)
            elif diferencia > 60:
                if info["status"] != "Desconectado Reintentando":
                    computadoras[id_pc]["status"] = "Desconectado Reintentando"
                    hubo_cambios = True

                if not info.get("alerta_1m_enviada", False):
                    historial_fallas.append({"id_pc": id_pc, "fecha_falla": ahora_str, "detalle": "Desconectado Reintentando (Inactividad > 1m)"})
                    computadoras[id_pc]["alerta_1m_enviada"] = True
                    hubo_cambios = True
                    enviar_correo_alerta(id_pc, "Desconectado Reintentando (>1 min)")

            # CASO 1: Menos de 60 segundos -> ONLINE (Verde)
            else:
                if info["status"] != "Online":
                    computadoras[id_pc]["status"] = "Online"
                    hubo_cambios = True

        except Exception as e:
            print(f"Error procesando tiempos: {e}")

    if hubo_cambios:
        guardar_datos_locales()


@app.route("/", methods=["GET"])
def inicio():
    return "Servidor Monitor Activo"


@app.route("/heartbeat", methods=["POST"])
def heartbeat():
    try:
        datos = request.get_json()
        if not datos or "id_pc" not in datos:
            return jsonify({"error": "Falta el id_pc"}), 400

        id_pc = datos["id_pc"]
        zona_mx = ZoneInfo("America/Mexico_City")
        ahora = datetime.now(zona_mx).strftime("%Y-%m-%d %H:%M:%S")

        cargar_datos_locales()

        computadoras[id_pc] = {
            "status": "Online", 
            "ultima_conexion": ahora,
            "alerta_1m_enviada": False,
            "alerta_3m_enviada": False
        }
        
        guardar_datos_locales()
        return jsonify({"mensaje": "Heartbeat recibido"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================================================================
# NUEVO: ENDPOINT PARA RESTAURAR RESPALDOS JSON EN LA VERSIÓN GRATUITA
# =========================================================================
@app.route("/cargar-respaldo", methods=["POST"])
def cargar_respaldo():
    """Permite subir los archivos descargados para no perder historial al actualizar"""
    global computadoras, historial_fallas
    try:
        if 'archivo_computadoras' in request.files:
            file_comp = request.files['archivo_computadoras']
            if file_comp.filename != '':
                computadoras = json.load(file_comp)
                
        if 'archivo_fallas' in request.files:
            file_fallas = request.files['archivo_fallas']
            if file_fallas.filename != '':
                historial_fallas = json.load(file_fallas)
                
        guardar_datos_locales()
        return """<script>alert('¡Respaldo cargado con éxito!'); window.location.href='/estados';</script>"""
    except Exception as e:
        return f"Error al cargar respaldo: {e}", 500


# ==========================================
# ENDPOINTS PARA EXPORTACIÓN DE REPORTES
# ==========================================

@app.route("/descargar/json/<tipo>", methods=["GET"])
def descargar_json(tipo):
    """Permite descargar el archivo de texto real para respaldar en tu PC"""
    cargar_datos_locales()
    if tipo == "fallas":
        data = json.dumps(historial_fallas, ensure_ascii=False, indent=4)
        filename = "historial_fallas_db.json"
    else:
        data = json.dumps(computadoras, ensure_ascii=False, indent=4)
        filename = "computadoras_db.json"
        
    response = Response(data, mimetype="application/json")
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response

@app.route("/descargar/excel/<tipo>", methods=["GET"])
def descargar_excel(tipo):
    cargar_datos_locales()
    output = io.StringIO()
    output.write('\ufeff') 
    
    if tipo == "fallas":
        output.write("ID Computadora,Fecha de Falla,Detalle\n")
        for f in historial_fallas:
            output.write(f"{f['id_pc']},{f['fecha_falla']},{f['detalle']}\n")
        filename = f"historial_fallas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    else:
        output.write("ID Computadora,Estatus Actual,Última Conexión\n")
        verificar_y_actualizar_estados()
        for id_pc, info in computadoras.items():
            output.write(f"{id_pc},{info['status']},{info['ultima_conexion']}\n")
        filename = f"estatus_actual_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


@app.route("/descargar/pdf/<tipo>", methods=["GET"])
def descargar_pdf(tipo):
    cargar_datos_locales()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    story = []
    
    styles = getSampleStyleSheet()
    titulo_estilo = styles['Heading1']
    titulo_estilo.textColor = colors.HexColor("#2c3e50")
    
    zona_mx = ZoneInfo("America/Mexico_City")
    fecha_reporte = datetime.now(zona_mx).strftime("%Y-%m-%d %H:%M:%S")

    if tipo == "fallas":
        story.append(Paragraph(f"Historial de Fallas Acumuladas", titulo_estilo))
        story.append(Paragraph(f"Reporte generado el: {fecha_reporte}", styles['Normal']))
        story.append(Spacer(1, 15))
        
        datos_tabla = [["ID Computadora", "Fecha de Incidente", "Detalle"]]
        for f in historial_fallas:
            datos_tabla.append([f['id_pc'], f['fecha_falla'], f['detalle']])
    else:
        verificar_y_actualizar_estados()
        story.append(Paragraph(f"Reporte de Estatus Actual de Equipos", titulo_estilo))
        story.append(Paragraph(f"Reporte generado el: {fecha_reporte}", styles['Normal']))
        story.append(Spacer(1, 15))
        
        datos_tabla = [["ID Computadora", "Estado Actual", "Última Conexión"]]
        for id_pc, info in computadoras.items():
            datos_tabla.append([id_pc, info['status'], info['ultima_conexion']])

    if len(datos_tabla) == 1:
        datos_tabla.append(["Sin registros en el sistema", "-", "-"])

    tabla = Table(datos_tabla, colWidths=[140, 170, 210])
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#34495e")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#ddd")),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9f9f9")]),
    ]))
    
    story.append(tabla)
    doc.build(story)
    
    buffer.seek(0)
    filename = f"reporte_{tipo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response


@app.route("/estados", methods=["GET"])
def mostrar_estados():
    cargar_datos_locales()
    verificar_y_actualizar_estados()

    alerta_activa = "false"

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta http-equiv="refresh" content="15"> 
        <title>Monitoreo de Equipos</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; background-color: #f4f6f9; color: #333; }
            h1 { color: #2c3e50; margin-bottom: 5px; }
            .seccion-reportes { background: #fff; padding: 15px; margin-bottom: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
            .btn { padding: 6px 12px; border: none; border-radius: 4px; font-weight: bold; cursor: pointer; text-decoration: none; font-size: 13px; display: inline-block; }
            .btn-excel { background-color: #27ae60; color: white; }
            .btn-pdf { background-color: #c0392b; color: white; }
            .btn-json { background-color: #2980b9; color: white; }
            .btn-subir { background-color: #8e44ad; color: white; margin-left: 5px;}
            .buscador-container { margin-bottom: 20px; }
            #buscador { padding: 10px; width: 300px; font-size: 16px; border: 1px solid #ccc; border-radius: 4px; }
            table { width: 100%; border-collapse: collapse; background-color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1); border-radius: 8px; overflow: hidden; }
            th, td { padding: 12px 15px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background-color: #34495e; color: white; }
            tr:hover { background-color: #f1f1f1; }
            .badge { padding: 6px 12px; border-radius: 20px; font-weight: bold; font-size: 13px; display: inline-block; }
            .online { background-color: #d4edda; color: #155724; }
            .reintentando { background-color: #ffe8cc; color: #d97706; }
            .offline { background-color: #f8d7da; color: #721c24; }
            .lbl-reporte { font-weight: bold; color: #555; }
        </style>
    </head>
    <body>

        <h1>📋 Panel de Monitoreo de Equipos</h1>
        <p style="color: #7f8c8d; margin-top:0; margin-bottom:25px;">Actualización automática cada 15 segundos</p>
        
        <div class="seccion-reportes">
            <span class="lbl-reporte">Estatus Actual:</span>
            <a href="/descargar/excel/estatus" class="btn btn-excel">📥 Excel</a>
            <a href="/descargar/pdf/estatus" class="btn btn-pdf">📄 PDF</a>
            <a href="/descargar/json/estatus" class="btn btn-json" title="Descargar respaldo técnico">💾 Resp. JSON</a>
            
            <span class="lbl-reporte" style="margin-left: 20px;">Historial de Fallas:</span>
            <a href="/descargar/excel/fallas" class="btn btn-excel">📥 Excel (Hist)</a>
            <a href="/descargar/pdf/fallas" class="btn btn-pdf">📄 PDF (Hist)</a>
            <a href="/descargar/json/fallas" class="btn btn-json" title="Descargar respaldo técnico">💾 Resp. JSON</a>
        </div>

        <div class="seccion-reportes" style="background: #fdf2fa; border: 1px dashed #8e44ad;">
            <form action="/cargar-respaldo" method="POST" enctype="multipart/form-data" style="display: flex; align-items: center; gap: 10px; font-size: 13px;">
                <span class="lbl-reporte" style="color: #8e44ad;">🛠️ Herramienta Antiborrado (Subir Respaldos JSON si actualizas Render):</span>
                <label>PCs: <input type="file" name="archivo_computadoras" accept=".json"></label>
                <label>Fallas: <input type="file" name="archivo_fallas" accept=".json"></label>
                <button type="submit" class="btn btn-subir">⚡ Cargar Datos</button>
            </form>
        </div>

        <div class="buscador-container">
            <input type="text" id="buscador" onkeyup="filtrarTabla()" placeholder="Buscar equipo por nombre (ej. 17)...">
        </div>

        <table id="tabla-equipos">
            <thead>
                <tr>
                    <th>Nombre de la Computadora</th>
                    <th>Estado</th>
                    <th>Última Actualización</th>
                    <th>Indicador</th>
                </tr>
            </thead>
            <tbody>
    """

    for id_pc, info in computadoras.items():
        if info["status"] == "Online":
            clase_status = "online"
            texto_status = "Online"
            icono = "✔️"
        elif info["status"] == "Desconectado Reintentando":
            clase_status = "reintentando"
            texto_status = "Desconectado Reintentando..."
            icono = "❓"
        else:
            clase_status = "offline"
            texto_status = "Desconectado"
            icono = "❌"
            alerta_activa = "true" 

        html += f"""
                <tr>
                    <td><b>{id_pc}</b></td>
                    <td><span class="badge {clase_status}">{texto_status}</span></td>
                    <td>{info['ultima_conexion']}</td>
                    <td style="font-size: 20px; padding-left: 25px;">{icono}</td>
                </tr>
        """

    html += f"""
            </tbody>
        </table>

        <script>
            const debeSonar = {alerta_activa};
            let alarmaIntervalo = null;
            
            if (debeSonar) {{
                window.addEventListener('click', iniciarAlarma10Segundos);
                setTimeout(iniciarAlarma10Segundos, 500);
            }}

            function iniciarAlarma10Segundos() {{
                if (alarmaIntervalo) return; 

                try {{
                    const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
                    
                    function emitirPitido() {{
                        const oscillator = audioCtx.createOscillator();
                        const gainNode = audioCtx.createGain();

                        oscillator.connect(gainNode);
                        gainNode.connect(audioCtx.destination);

                        oscillator.type = 'sine';
                        oscillator.frequency.setValueAtTime(880, audioCtx.currentTime); 
                        gainNode.gain.setValueAtTime(0.3, audioCtx.currentTime); 

                        oscillator.start();
                        oscillator.stop(audioCtx.currentTime + 0.3); 
                    }}

                    emitirPitido(); 
                    alarmaIntervalo = setInterval(emitirPitido, 600);

                    setTimeout(() => {{
                        clearInterval(alarmaIntervalo);
                        audioCtx.close();
                    }}, 10000);

                }} catch(e) {{
                    console.log("Audio Bloqueado por el navegador.");
                }}
            }}

            function filtrarTabla() {{
                let input = document.getElementById("buscador");
                let filter = input.value.toUpperCase();
                let table = document.getElementById("tabla-equipos");
                let tr = table.getElementsByTagName("tr");

                for (let i = 1; i < tr.length; i++) {{
                    let td = tr[i].getElementsByTagName("td")[0];
                    if (td) {{
                        let txtValue = td.textContent || td.innerText;
                        if (txtValue.toUpperCase().indexOf(filter) > -1) {{
                            tr[i].style.display = "";
                        }} else {{
                            tr[i].style.display = "none";
                        }}
                    }}
                }}
            }}
        </script>
    </body>
    </html>
    """
    return html


if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=puerto)