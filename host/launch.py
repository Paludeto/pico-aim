"""Inicializador rapido para o Shooter 3D e o ensaio hw_loop no Windows."""
import os
import subprocess
import sys
import time
import traceback

HOST_DIR = os.path.dirname(os.path.abspath(__file__))
if HOST_DIR not in sys.path:
    sys.path.insert(0, HOST_DIR)


def find_pico_port():
    import serial.tools.list_ports as lp
    for p in lp.comports():
        if p.vid == 0x1209 and p.pid == 0x0001:
            return p.device
    return None


def run_shooter(port):
    from common import protocol as P
    from tracker import winutil

    if not port:
        print("Nenhuma Raspberry Pi Pico (VID:PID 1209:0001) detectada.")
        print("Abrindo o Shooter 3D apenas com controle manual pelo mouse...")
        return subprocess.call([sys.executable, "-m", "testapp", "--mode", "shooter"], cwd=HOST_DIR)

    print(f"Raspberry Pi Pico detectada em {port}.")
    print("Abrindo janela do Shooter 3D...")
    app_proc = subprocess.Popen([sys.executable, "-m", "testapp", "--mode", "shooter"], cwd=HOST_DIR)
    try:
        t0 = time.perf_counter()
        region = None
        while region is None and time.perf_counter() - t0 < 12.0:
            if app_proc.poll() is not None:
                print(f"[ERRO] O testapp fechou inesperadamente (codigo {app_proc.returncode}).")
                return app_proc.returncode
            region = winutil.window_client_rect(P.WINDOW_TITLE)
            time.sleep(0.15)
        if region is None:
            print(f"[ERRO] Janela '{P.WINDOW_TITLE}' nao apareceu em 12 s.")
            return 1

        print(f"\nIniciando tracker em {port} (modo AUTOMATICO)...")
        print("Dica: de uma pressao CURTA no BOOTSEL da Pico para habilitar o aimbot.")
        print("Mantenha a janela do Shooter 3D visivel na tela! (Feche a janela 3D ou pressione 'q' aqui para sair)\n")
        trk_proc = subprocess.Popen([sys.executable, "-m", "tracker", "--port", port, "--mode", "auto"], cwd=HOST_DIR)
        try:
            while True:
                if app_proc.poll() is not None or trk_proc.poll() is not None:
                    break
                time.sleep(0.15)
        finally:
            if trk_proc.poll() is None:
                trk_proc.terminate()
                try:
                    trk_proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    trk_proc.kill()
        return trk_proc.returncode or 0
    finally:
        if app_proc.poll() is None:
            app_proc.terminate()


def run_hw_loop(port):
    if not port:
        print("[ERRO] Nenhuma Raspberry Pi Pico (VID:PID 1209:0001) encontrada.")
        print("Conecte a placa ou informe a porta manualmente: rodar_hw_loop.bat COM5")
        return 1
    # Verifica antes se a porta serial esta livre
    import serial
    try:
        s = serial.Serial(port, 115200, timeout=0.1)
        s.close()
    except serial.SerialException as e:
        print(f"[ERRO] Nao foi possivel abrir {port}: {e}")
        print("Verifique se o terminal do 'jogar_shooter3d.bat' (tracker) ainda esta aberto usando a porta e feche-o primeiro.")
        return 1
    print(f"Raspberry Pi Pico detectada em {port}.")
    print("Iniciando ensaio completo em malha fechada (hw_loop.py)...\n")
    return subprocess.call([sys.executable, os.path.join("tests", "hw_loop.py"), port], cwd=HOST_DIR)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "shooter"
    port = sys.argv[2] if len(sys.argv) > 2 else find_pico_port()
    if mode == "--check":
        print("OK | python:", sys.executable, "| pico:", port)
        return 0
    if mode == "hw_loop":
        return run_hw_loop(port)
    return run_shooter(port)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
