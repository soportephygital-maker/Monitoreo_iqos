from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import io
import os
import smtplib
from zoneinfo import ZoneInfo

# Importaciones nuevas para exportar archivos
from flask import Flask, Response, jsonify, make_response, request
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

app = Flask(__name__)

# Diccionarios y listas en memoria para almacenar estados e historiales
computadoras = {}
historial_fallas = []   # Registra solo cuando un equipo pasa a "Offline"
historial_estatus = []  # Registra todas las actualizaciones de estado (Online/Offline)

# Configuración de alertas por correo usando las variables de entorno de Render
EMAIL_USER = os.environ.get("EMAIL_USER", "soportephygital@gmail.com")
EMAIL_PASS = os.environ.get("EMAIL_PASS", "obfl nmnm izhl kndg")
EMAIL_DESTINO = "soportephygital@gmail.com"


def enviar_correo_alerta(id_pc):
    """Función para enviar un correo seguro vía SMTP TLS cuando una PC se desconecta"""
    if not EMAIL_PASS:
        print("[ALERTA CORREO] No se pudo enviar: Falta configurar la variable EMAIL_PASS en Render.")
        return

    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_USER
        msg["To"] = EMAIL_DESTINO
        msg["Subject"] = f"🚨 ALERTA: {id_pc} se encuentra FUERA DE LÍNEA"

        cuerpo = f"El sistema de monitoreo informa que el equipo '{id_pc}' ha dejado de reportarse por más de 2 minutos."
        msg.attach(MIMEText(cuerpo, "plain"))

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, EMAIL_DESTINO, msg.as_string())
        server.quit()
        print(f"[CORREO] ¡Alerta enviada con éxito para {id_pc}!")
    except Exception as e:
        print(f"[CORREO ERROR] No se pudo enviar el correo: {e}")


def verificar_y_actualizar_estados():
    """Revisa los tiempos y marca como Offline si pasaron más de 2 minutos (120 segundos)"""
    zona_mx = ZoneInfo("America/Mexico_City")
    ahora = datetime.now(zona_mx)

    for id_pc, info in computadoras.items():
        try:
            ult_conexion = datetime.strptime(
                info["ultima_conexion"], "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=zona_mx)
            diferencia = (ahora - ult_conexion).total_seconds()

            if diferencia > 120 and info["status"] == "Online":
                ahora_str = ahora.strftime("%Y-%m-%d %H:%M:%S")
                computadoras[id_pc]["status"] = "Offline"
                
                # Registrar en el historial de fallas y de estatus
                registro_falla = {"id_pc": id_pc, "fecha_falla": ahora_str, "detalle": "Inactividad > 120s"}
                historial_fallas.append(registro_falla)
                historial_estatus.append({"id_pc": id_pc, "status": "Offline", "fecha": ahora_str})
                
                enviar_correo_alerta(id_pc)
        except Exception as e:
            print(f"Error procesando tiempos para {id_pc}: {e}")


@app.route("/", methods=["GET"])
def inicio():
    return "Servidor Monitor Activo y Corriendo."


@app.route("/heartbeat", methods=["POST"])
def heartbeat():
    try:
        datos = request.get_json()
        if not datos or "id_pc" not in datos:
            return jsonify({"error": "Falta el id_pc"}), 400

        id_pc = datos["id_pc"]
        zona_mx = ZoneInfo("America/Mexico_City")
        ahora = datetime.now(zona_mx).strftime("%Y-%m-%d %H:%M:%S")

        # Detectar si el estado anterior era Offline para registrar el regreso a Online
        estado_anterior = computadoras.get(id_pc, {}).get("status", "Offline")
        
        computadoras[id_pc] = {"status": "Online", "ultima_conexion": ahora}
        
        # Registrar cambio en el historial general si el equipo revive
        if estado_anterior == "Offline":
            historial_estatus.append({"id_pc": id_pc, "status": "Online", "fecha": ahora})
            
        return jsonify({"mensaje": "Heartbeat recibido"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==========================================
# ENRUTAMIENTO PARA REPORTES Y EXPORTACIÓN
# ==========================================

@app.route("/descargar/excel/<tipo>", methods=["GET"])
def descargar_excel(tipo):
    """Genera un archivo CSV (compatible con Excel) codificado para admitir caracteres especiales"""
    output = io.StringIO()
    # Escribir la firma BOM para que Excel detecte UTF-8 correctamente automáticamente
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
    """Genera un reporte limpio en formato PDF usando ReportLab"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    story = []
    
    styles = getSampleStyleSheet()
    titulo_estilo = styles['Heading1']
    titulo_estilo.textColor = colors.HexColor("#2c3e50")
    
    zona_mx = ZoneInfo("America/Mexico_City")
    fecha_reporte = datetime.now(zona_mx).strftime("%Y-%m-%d %H:%M:%S")

    if tipo == "fallas":
        story.append(Paragraph(f"Historial de Fallas (Equipos Offline)", titulo_estilo))
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

    # Si la tabla no tiene registros más allá de la cabecera
    if len(datos_tabla) == 1:
        datos_tabla.append(["Sin registros", "-", "-"])

    tabla = Table(datos_tabla, colWidths=[150, 180, 180])
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#34495e")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor("#f4f6f9")),
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
    verificar_y_actualizar_estados()

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
            .seccion-reportes { background: #fff; padding: 15px; margin-bottom: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); display: flex; gap: 10px; align-items: center; }
            .btn { padding: 10px 15px; border: none; border-radius: 4px; font-weight: bold; cursor: pointer; text-decoration: none; font-size: 14px; display: inline-block; }
            .btn-excel { background-color: #27ae60; color: white; }
            .btn-excel:hover { background-color: #219653; }
            .btn-pdf { background-color: #c0392b; color: white; }
            .btn-pdf:hover { background-color: #a32e22; }
            .buscador-container { margin-bottom: 20px; }
            #buscador { padding: 10px; width: 300px; font-size: 16px; border: 1px solid #ccc; border-radius: 4px; }
            table { width: 100%; border-collapse: collapse; background-color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1); border-radius: 8px; overflow: hidden; }
            th, td { padding: 12px 15px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background-color: #34495e; color: white; }
            tr:hover { background-color: #f1f1f1; }
            .badge { padding: 6px 12px; border-radius: 20px; font-weight: bold; font-size: 14px; display: inline-block; }
            .online { background-color: #d4edda; color: #155724; }
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
            
            <span class="lbl-reporte" style="margin-left: 20px;">Historial de Fallas:</span>
            <a href="/descargar/excel/fallas" class="btn btn-excel">📥 Excel (Historial)</a>
            <a href="/descargar/pdf/fallas" class="btn btn-pdf">📄 PDF (Historial)</a>
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
            icono = "✔️"
        else:
            clase_status = "offline"
            icono = "❌"

        html += f"""
                <tr>
                    <td><b>{id_pc}</b></td>
                    <td><span class="badge {clase_status}">{info['status']}</span></td>
                    <td>{info['ultima_conexion']}</td>
                    <td style="font-size: 20px; padding-left: 25px;">{icono}</td>
                </tr>
        """

    html += """
            </tbody>
        </table>

        <script>
            function filtrarTabla() {
                let input = document.getElementById("buscador");
                let filter = input.value.toUpperCase();
                let table = document.getElementById("tabla-equipos");
                let tr = table.getElementsByTagName("tr");

                for (let i = 1; i < tr.length; i++) {
                    let td = tr[i].getElementsByTagName("td")[0];
                    if (td) {
                        let txtValue = td.textContent || td.innerText;
                        if (txtValue.toUpperCase().indexOf(filter) > -1) {
                            tr[i].style.display = "";
                        } else {
                            tr[i].style.display = "none";
                        }
                    }
                }
            }
        </script>
    </body>
    </html>
    """
    return html


if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=puerto)