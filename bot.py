import sys
import json
import time
import argparse
import re
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple
from client import UTNInscripcionClient

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Renderizador de Reloj Digital ASCII (100% compatible con cualquier terminal Windows/Linux)
ASCII_DIGITS = {
    '0': [" ### ", "#   #", "#   #", "#   #", " ### "],
    '1': ["  #  ", " ##  ", "  #  ", "  #  ", " ### "],
    '2': [" ### ", "    #", " ### ", "#    ", "#####"],
    '3': [" ### ", "    #", " ### ", "    #", " ### "],
    '4': ["#   #", "#   #", "#####", "    #", "    #"],
    '5': ["#####", "#    ", "#### ", "    #", "#### "],
    '6': [" ### ", "#    ", "#### ", "#   #", " ### "],
    '7': ["#####", "    #", "   # ", "  #  ", "  #  "],
    '8': [" ### ", "#   #", " ### ", "#   #", " ### "],
    '9': [" ### ", "#   #", " ####", "    #", " ### "],
    ':': ["   ", " o ", "   ", " o ", "   "]
}

def render_ascii_clock(time_str: str) -> str:
    lines = ["", "", "", "", ""]
    for char in time_str:
        digit_lines = ASCII_DIGITS.get(char, ["     "] * 5)
        for i in range(5):
            lines[i] += digit_lines[i] + " "
    return "\n".join(lines)


def load_config(config_path: str = "config.json") -> Dict[str, Any]:
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[❌] Archivo {config_path} no encontrado.")
        sys.exit(1)
    except Exception as e:
        print(f"[❌] Error al leer {config_path}: {e}")
        sys.exit(1)

def print_header():
    print("=" * 65)
    print("        anotateBOT - UTN FRC Inscripcion por API HTTP")
    print("=" * 65)

def parse_server_breakdown(client: UTNInscripcionClient, raw_response: str, config: Dict[str, Any]) -> List[str]:
    """
    Analiza la respuesta detallada del servidor de la UTN y determina
    materia por materia cuáles consiguieron cupo/posición y cuáles no.
    """
    lines = []
    deseadas = config.get("comisiones_deseadas", [])
    
    # Mapear códigos resueltos
    for sel in deseadas:
        mat_name = sel.get("materia", "Materia")
        curso = sel.get("curso", "")
        code_resolved = client.resolve_materia_payload([sel])
        
        if code_resolved and code_resolved in raw_response:
            # Buscar estado asociado en el string de respuesta
            if "SIN CUPO" in raw_response.upper() or "SIN LUGAR" in raw_response.upper():
                lines.append(f"[❌] {mat_name} ({curso}): SIN CUPO DISPONIBLE")
            else:
                lines.append(f"[✔] {mat_name} ({curso}): PROCESADA EN COLA / CONSEGUIDA")
        elif code_resolved:
            lines.append(f"[✔] {mat_name} ({curso}): SOLICITUD ENVIADA (Codigo: {code_resolved})")
        else:
            lines.append(f"[❌] {mat_name} ({curso}): NO FIGURA EN LA OFERTA VIVA")
            
    return lines

def cmd_list(client: UTNInscripcionClient, config: Dict[str, Any]):
    print("\n[+] Autenticando en UTN FRC...")
    if not client.login(config["usuario"], config.get("dominio", "sistemas"), config["clave"]):
        print("[❌] Error de autenticacion. Verifique su legajo y clave.")
        return
    print("[✔] Login exitoso.")
    
    client.init_cursado(config["usuario"])
    guid, materias = client.get_comisiones()
    
    if not materias:
        print("[!] La consulta en vivo aun no fue abierta por la facultad.")
        return
        
    print(f"\n[✔] Oferta cargada correctamente (GUID: {guid})")
    print("=" * 65)
    print(f"{'CODIGO':<12} | {'MATERIA':<35} | {'CURSOS DISPONIBLES'}")
    print("-" * 65)
    
    for m in materias:
        codigo = m.get("CODIGO", "N/A")
        nombre = m.get("Name", "N/A")
        structure = m.get("Structure", "")
        struct_parsed = client.parse_structure(structure)
        
        cursos_list = []
        for st in struct_parsed:
            c_entry = f"{st['curso']} (Com:{st['comision_code']})"
            if c_entry not in cursos_list:
                cursos_list.append(c_entry)
                
        cursos_str = ", ".join(cursos_list)
        if len(nombre) > 34:
            nombre = nombre[:31] + "..."
        print(f"{codigo:<12} | {nombre:<35} | {cursos_str}")
        
    print("=" * 65)

def cmd_dry_run(client: UTNInscripcionClient, config: Dict[str, Any]):
    print("\n[+] MODO DRY-RUN (Simulacion)")
    print("[+] Autenticando...")
    if not client.login(config["usuario"], config.get("dominio", "sistemas"), config["clave"]):
        print("[❌] Error de autenticacion.")
        return
    print("[✔] Login exitoso.")
    
    client.init_cursado(config["usuario"])
    guid, materias = client.get_comisiones()
    
    deseadas = config.get("comisiones_deseadas", [])
    directas = config.get("codigos_directos", [])
    payload = client.resolve_materia_payload(list(deseadas) + list(directas))
    
    print("\n" + "=" * 65)
    print("RESUMEN DE SIMULACION:")
    print(f"  • Payload a enviar: {payload if payload else '(Ninguno resuelto)'}")
    print(f"  • GUID listo: {guid}")
    print(f"  • Telegram: {'CONECTADO' if client.telegram_token else 'NO CONFIGURADO'}")
    print("=" * 65)
    
    if client.telegram_token:
        client.send_telegram("anotateBOT: Prueba Dry-Run realizada con exito.")

def cmd_sniper(client: UTNInscripcionClient, config: Dict[str, Any], target_time_str: str = None):
    now = datetime.now()
    
    # Si no se pasa la flag --time (o se omite), dispara la inscripcion inmediatamente
    if not target_time_str:
        print("\n[+] MODO SNIPER INMEDIATO (Sin temporizador)")
        print("🚀 Disparando inscripcion en este instante para todas tus materias...\n")
        target_dt = now
    else:
        print(f"\n[+] MODO SNIPER TEMPORIZADO (Hora Objetivo: {target_time_str})")
        target_time = datetime.strptime(target_time_str, "%H:%M:%S").time()
        target_dt = datetime.combine(now.date(), target_time)
        
        if target_dt < now:
            diff_seconds = (now - target_dt).total_seconds()
            if diff_seconds < 7200:
                print(f"\n[!] La hora objetivo ({target_time_str}) ya paso hoy (hace {int(diff_seconds/60)} min).")
                print("[+] Disparando inscripcion DIRECTA E INMEDIATA en este instante...\n")
                target_dt = now
            else:
                target_dt += timedelta(days=1)



    print("[+] Autenticando en UTN FRC...")
    if not client.login(config["usuario"], config.get("dominio", "sistemas"), config["clave"]):
        print("[❌] Error de autenticacion.")
        return
    print("[✔] Login exitoso.")
    
    client.init_cursado(config["usuario"])
    guid, materias = client.get_comisiones()
    
    deseadas = config.get("comisiones_deseadas", [])
    directas = config.get("codigos_directos", [])
    payload = client.resolve_materia_payload(list(deseadas) + list(directas))
    
    if client.telegram_token:
        client.send_telegram(f"anotateBOT Iniciado | Legajo: {config['usuario']} | Objetivo: {target_time_str}")

    print("\n" + "=" * 65)
    print("ESTADO DEL MONITOR:")
    print(f"  • Usuario: {config['usuario']}")
    print(f"  • Hora Objetivo: {target_dt.strftime('%H:%M:%S')}")
    print(f"  • Payload Inicial: {payload if payload else '(Pendiente de apertura)'}")
    print(f"  • Telegram: {'Activo' if client.telegram_token else 'Inactivo'}")
    print("=" * 65)
    
    notified_5min = False
    notified_1min = False
    
    # Bucle con Reloj Digital ASCII Gigante en pantalla
    while True:
        current = datetime.now()
        seconds_left = (target_dt - current).total_seconds()
        
        if seconds_left <= 10:
            break
            
        current_time_str = current.strftime('%H:%M:%S')
        target_time_display = target_dt.strftime('%H:%M:%S')
        sec_display = int(seconds_left)
        
        # Limpiar consola e imprimir Reloj ASCII Gigante
        os.system('cls' if os.name == 'nt' else 'clear')
        print_header()
        print(render_ascii_clock(current_time_str))
        print("=" * 65)
        print(f"  OBJETIVO: {target_time_display} | FALTAN: {sec_display} segundos | SESION ACTIVA")
        print("=" * 65)
        
        if 295 <= seconds_left <= 300 and not notified_5min:
            client.send_telegram("anotateBOT: Quedan 5 minutos para el inicio de inscripcion.")
            notified_5min = True
            
        if 55 <= seconds_left <= 60 and not notified_1min:
            client.send_telegram("anotateBOT: Queda 1 MINUTO para el disparo.")
            notified_1min = True

        if int(seconds_left) % 45 == 0 and seconds_left > 15:
            guid, materias = client.get_comisiones()
            payload_updated = client.resolve_materia_payload(list(deseadas) + list(directas))
            if payload_updated and payload_updated != payload:
                payload = payload_updated
                client.send_telegram(f"anotateBOT: Nueva oferta viva detectada -> {payload}")
                
        time.sleep(1.0)

    os.system('cls' if os.name == 'nt' else 'clear')
    print_header()
    print("[+] Refrescando GUID final a 5s del objetivo...")
    guid, materias = client.get_comisiones()
    payload_final = client.resolve_materia_payload(list(deseadas) + list(directas))
    if payload_final:
        payload = payload_final
        
    print(f"  • GUID: {client.guid}")
    print(f"  • Payload: {payload}")
    
    # Espera activa sub-milisegundo
    while datetime.now() < target_dt:
        pass
        
    shot_time = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"\n[+] Disparando rafaga a las {shot_time}...")
    client.send_telegram(f"anotateBOT: Disparando inscripcion a las {shot_time}")
    
    results = []
    petition_ids = []
    
    for i in range(3):
        res = client.enviar_inscripcion(payload)
        results.append(res)
        print(f"  [Disparo {i+1}] {res['time_ms']} ms | Status {res['status_code']}")
        
        if "data" in res and isinstance(res["data"], dict):
            resp_str = res["data"].get("Respuesta", "")
            match = re.search(r"(0[0-9A-Z]{6,}-[0-9]+)", resp_str)
            if match:
                petition_ids.append(match.group(1))
        time.sleep(0.08)

    res_first = results[0]
    print(f"\n[✔] Respuesta del servidor ({res_first['time_ms']} ms)")
    
    # Desglose materia por materia
    breakdown = parse_server_breakdown(client, res_first['raw_response'], config)
    print("\nDESGLOSE POR MATERIA:")
    for b in breakdown:
        print(f"  {b}")
        
    tg_breakdown_str = "\n".join(breakdown)
    client.send_telegram(f"anotateBOT: Inscripcion Enviada en {res_first['time_ms']} ms!\n\n{tg_breakdown_str}")
    
def cmd_demo(client: UTNInscripcionClient, config: Dict[str, Any]):
    print("\n[+] MODO DEMO - SIMULACION INTERACTIVA EN TIEMPO REAL")
    print("[+] Inicializando simulacion de los ultimos 10 segundos antes de las 17:00:00...\n")
    time.sleep(2)
    
    # 1. Simulación de los últimos 10 segundos con Reloj Digital ASCII
    target_dt = datetime.now() + timedelta(seconds=10)
    
    while True:
        current = datetime.now()
        seconds_left = (target_dt - current).total_seconds()
        
        if seconds_left <= 0:
            break
            
        current_time_str = current.strftime('%H:%M:%S')
        sec_display = max(0, int(seconds_left))
        
        os.system('cls' if os.name == 'nt' else 'clear')
        print_header()
        print(render_ascii_clock(current_time_str))
        print("=" * 65)
        print(f"  OBJETIVO: 17:00:00 | FALTAN: {sec_display:>2} segundos | SESION ACTIVA")
        print("=" * 65)
        time.sleep(0.5)
        
    os.system('cls' if os.name == 'nt' else 'clear')
    print_header()
    shot_time = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"[+] Disparando rafaga a las {shot_time}...")
    if client.telegram_token:
        client.send_telegram(f"anotateBOT Demo: Disparando inscripcion a las {shot_time}")
    
    time.sleep(0.3)
    print("  [Disparo 1] 42.1 ms | Status 200")
    print("  [Disparo 2] 45.8 ms | Status 200")
    print("  [Disparo 3] 48.3 ms | Status 200")
    
    print("\n[✔] Respuesta inicial del servidor (42.1 ms)")
    print("\nDESGLOSE INICIAL POR MATERIA (2 Conseguidas, 2 Pendientes):")
    print("  [✔] Ingenieria y Calidad de Software (4K2): PROCESADA EN COLA / CONSEGUIDA")
    print("  [✔] Seguridad en el Desarrollo de Software (5K4): PROCESADA EN COLA / CONSEGUIDA")
    print("  [❌] Tecnologias para la Automatizacion (4K2): SIN CUPO / PENDIENTE")
    print("  [❌] DevOps (4K4): SIN CUPO / PENDIENTE")
    
    if client.telegram_token:
        client.send_telegram("anotateBOT Demo: Respuesta Inicial -> 2 materias conseguidas (ICW, SDS), 2 pendientes (TA, DO).")
        
    time.sleep(3)
    print("\n[+] REINTENTO SELECTIVO ACTIVADO (Solo materias pendientes: TA, DO)")
    print("    (Las materias conseguidas ICW y SDS estan 100% seguras y no se modifican)")
    
    if client.telegram_token:
        client.send_telegram("anotateBOT Demo: Reintentando solo materias pendientes (TA, DO)...")
        
    time.sleep(3)
    print("  [Reintento 1] 44.2 ms | [✔] Tecnologias para la Automatizacion (4K2): CONSEGUIDA EN REINTENTO")
    print("\nDESGLOSE ACTUALIZADO (3 Conseguidas, 1 Pendiente):")
    print("  [✔] Ingenieria y Calidad de Software (4K2): CONSEGUIDA")
    print("  [✔] Seguridad en el Desarrollo de Software (5K4): CONSEGUIDA")
    print("  [✔] Tecnologias para la Automatizacion (4K2): CONSEGUIDA EN REINTENTO")
    print("  [❌] DevOps (4K4): SIN CUPO / PENDIENTE (Falta 1)")
    
    if client.telegram_token:
        client.send_telegram("anotateBOT Demo: Reintento 1 -> TA conseguida! Queda solo DevOps.")
        
    time.sleep(3)
    print("  [Reintento 2] 41.8 ms | [✔] DevOps (4K4): CONSEGUIDA EN REINTENTO")
    
    print("\n" + "=" * 65)
    print("[✔] ESTADO FINAL: 🎉 ¡100% DE LAS MATERIAS INSCRIPTAS CON EXITO!")
    print("  [✔] Ingenieria y Calidad de Software (4K2): CONSEGUIDA")
    print("  [✔] Seguridad en el Desarrollo de Software (5K4): CONSEGUIDA")
    print("  [✔] Tecnologias para la Automatizacion (4K2): CONSEGUIDA")
    print("  [✔] DevOps (4K4): CONSEGUIDA")
    print("=" * 65)
    
    if client.telegram_token:
        client.send_telegram("anotateBOT Demo: 🎉 ¡100% DE TUS MATERIAS INSCRIPTAS CON EXITO!\n\n✔ ICW (4K2)\n✔ SDS (5K4)\n✔ TA (4K2)\n✔ DO (4K4)")



def main():
    print_header()
    parser = argparse.ArgumentParser(description="anotateBOT - UTN FRC API HTTP")
    parser.add_argument("modo", choices=["list", "dry-run", "sniper", "demo"], 
                        help="Modo de ejecucion: list, dry-run, sniper, demo")
    parser.add_argument("--time", type=str, default=None, help="Hora objetivo para modo sniper (HH:MM:SS). Si se omite, dispara inmediatamente.")

    parser.add_argument("--config", type=str, default="config.json", help="Ruta al archivo config.json")
    
    args = parser.parse_args()
    config = load_config(args.config)
    client = UTNInscripcionClient()
    
    telegram_token = config.get("telegram_token", "")
    telegram_chat_id = config.get("telegram_chat_id", "")
    if telegram_token and telegram_chat_id:
        client.setup_telegram(telegram_token, telegram_chat_id)
        
    if args.modo == "list":
        cmd_list(client, config)
    elif args.modo == "dry-run":
        cmd_dry_run(client, config)
    elif args.modo == "sniper":
        cmd_sniper(client, config, args.time)
    elif args.modo == "demo":
        cmd_demo(client, config)


if __name__ == "__main__":
    main()

