# Guia de Funcionamento e Estrutura do Código

Este guia explica de forma direta como o sistema funciona de ponta a ponta e o que cada arquivo do repositório faz.

## 1. Funcionamento geral

A malha fechada percorre quatro etapas continuamente:

```text
[testapp: Shooter 3D (60 Hz)]
        │  imagem da janela (núcleo magenta em tx, ty)
        ▼
[tracker: captura + HSV + GetCursorPos] ──► USB CDC (quadro MEAS com ex, ey)
        ▲                                              │
        │  USB HID (mouse relativo, 1 kHz)             ▼
[Windows desloca o ponteiro] ◄──────────── [RP2040: Core 0 + Core 1 (PID 1 kHz)]
```

1. **Cena 3D (`host/testapp`):** renderiza um estande de tiro 3D em Pygame a 60 Hz. Um robô-alvo movimenta-se pelo cenário levando um núcleo circular magenta posicionado exatamente em `(target_x, target_y)`.
2. **Visão e erro (`host/tracker`):** localiza a área cliente da janela `"Rastreador - app de teste"`, captura os pixels via `dxcam` ou `mss`, segmenta o maior contorno magenta em HSV para achar o centroide `(tx, ty)`, lê o cursor do Windows via `GetCursorPos` e envia `ex = tx - cx`, `ey = ty - cy` pela porta serial virtual USB CDC.
3. **Controle em tempo real (`firmware/`):** o core 0 do RP2040 decodifica os quadros CDC e os repassa por fila ao core 1. A cada 1 ms, o core 1 atualiza o estimador de latência (compensando os comandos já enviados que ainda estão em trânsito) e calcula o passo `(dx, dy)` pelo PID em ponto fixo Q16.16.
4. **Atuação (`USB HID`):** se a saída estiver habilitada pelo botão `BOOTSEL` e o modo estiver em `AUTOMÁTICO`, o core 0 envia relatórios HID relativos ao Windows, deslocando o ponteiro sobre o alvo na tela.

### Por que a interface 3D não atrapalha o rastreamento

- **Cursor livre:** o ponteiro do Windows não é travado no centro da janela, preservando a relação linear entre contagens HID e pixels lidos por `GetCursorPos`. A câmera 3D aplica apenas paralaxe suave.
- **Projeção exata:** a câmera calcula o ponto 3D cuja projeção em perspectiva cai exatamente sobre `(target_x, target_y)`, mantendo o corpo do robô e sua sombra coerentes em 3D sem desviar o alvo.
- **Paleta controlada e ordem de desenho:** cenário, arma, efeitos de disparo, radar e HUD evitam completamente a faixa de cor magenta do detector. Além disso, o núcleo magenta é desenhado por último (acima de HUD e arma) e o retículo possui centro aberto, garantindo detecção limpa em qualquer posição da tela.

---

## 2. O que cada arquivo faz

### Firmware do RP2040 (`firmware/`)

- `CMakeLists.txt` — configuração de build com Pico SDK (C11) e `copy_to_ram` (executa o firmware inteiro da RAM).
- `board_config.h` — pinagem (`GP25` LED, `GP2`/`GP3` debug), períodos (1 ms controle, 10 ms UI, 1 s watchdog), tamanhos de filas e IDs USB.
- `prebuilt/cursor_tracker.uf2` — binário pronto para gravar na Raspberry Pi Pico.
- `src/main.c` — laço principal do **core 0**: TinyUSB (`tud_task`), leitura CDC, envio de telemetria, acumulação e disparo de relatórios HID, UI, medição de carga e watchdog.
- `src/usb/tusb_config.h` e `usb_descriptors.c` — configuração do TinyUSB e descritores USB do dispositivo composto CDC + HID mouse (`bInterval = 1 ms`).
- `src/proto/crc8.c/.h` e `proto.c/.h` — cálculo de CRC-8 (`0x07`), parser byte a byte com ressincronização em `0xA5 0x5A` e montagem dos quadros `TELEM`, `ACK` e `PARAMS`.
- `src/ctrl/fixed.h` — aritmética inteira Q16.16, saturação e truncamento.
- `src/ctrl/params.c/.h` — valores padrão e validação de faixas dos 9 parâmetros configuráveis.
- `src/ctrl/estimator.c/.h` — estimador multitaxa de latência com buffer circular de 128 comandos por eixo.
- `src/ctrl/pid.c/.h` — PID discreto em Q16.16 com derivada filtrada, zona morta, saturação em ±127, anti-windup e resíduo fracionário.
- `src/ctrl/loop.c/.h` — executa um passo completo de 1 ms: aplica configurações, verifica failsafe de link (100 ms), roda o PID ou o sinal de identificação (degraus + PRBS7) e decima a telemetria a 200 Hz.
- `src/core1/core1.c/.h` — cria as filas inter-núcleo e executa `ctrl_loop_step()` dentro da interrupção de alarme de 1 kHz no **core 1**.
- `src/ui/bootsel.c`, `led.c`, `ui.c/.h` — timer de 10 ms no core 0 para ler o `BOOTSEL` (da RAM, com debounce de 30 ms e distinção entre toque curto e emergência de 1 s) e controlar os padrões do LED GP25.
- `src/app/app.c/.h` — máquina de estados do core 0, checagem de sequência `SEQ`, processamento de comandos CDC e reação a botão/USB.
- `src/app/persist.c/.h` — gravação e leitura dos parâmetros no último setor da flash com cabeçalho, CRC-8 e pausa coordenada do core 1.

### Software do PC (`host/`)

- `common/protocol.py` — espelha `proto.h` e `params.h`: constantes, CRC-8, empacotamento/decodificação de quadros, conversão física ↔ Q16.16 e `FrameParser`.
- `testapp/trajectories.py` — gera as trajetórias `step`, `ramp`, `sine`, `smooth` e `shooter`.
- `testapp/shooter3d.py` — renderizador 3D em Pygame (`Camera3D` e `Shooter3DScene`): arena em perspectiva, robô-alvo rígido, núcleo magenta seguro para HSV, carabina 3D com recuo e efeitos de disparo, mira tática, radar, HUD e mecânica de HP/respawn.
- `testapp/__main__.py` — interface CLI e laço de 60 Hz da janela gráfica, leitura do cursor Win32, alternância 3D/2D (`V`) e gravação de CSV por quadro.
- `tracker/winutil.py` — wrappers Win32 (`ctypes`) para DPI awareness, `GetCursorPos` e área cliente da janela do `testapp`.
- `tracker/capture.py` — captura de região da tela em BGR via `dxcam` com fallback para `mss`.
- `tracker/detect.py` — segmentação do alvo magenta em HSV (OpenCV) + centroide do maior contorno (com fallback em NumPy).
- `tracker/__main__.py` — laço de 60 Hz que captura a janela, calcula o erro, envia `MEAS` pela serial, grava logs e permite ajustar parâmetros pelo teclado.
- `analysis/identify.py` — estima ganho da planta $g$ e latência $L$ por mínimos quadrados a partir da telemetria de identificação.
- `analysis/metrics.py` — calcula overshoot, tempo de subida, acomodação (2%), erro em regime, RMS, atraso e defasagem a partir dos CSVs do `testapp` (com opção `--plot`).
- `tests/test_host.py` — testes Python sem hardware (protocolo, detecção HSV, trajetórias, análise sobre `docs/medicoes/` e validação de detecção sobre quadros 3D).
- `tests/test_ctrl.c`, `sil_shim.c/.h` e `tests.mk` — testes unitários nativos em C (2165 verificações) do firmware portável compilado no PC.
- `tests/hw_check.py` — valida protocolo, período de 1 ms, failsafe e flash na Pico sem movimentar o cursor.
- `tests/hw_loop.py` — executa o ensaio automatizado completo em malha fechada (`ident`, `step`, `sine`, `ramp`, `smooth`).
- `launch.py`, `jogar_shooter3d.bat` e `rodar_hw_loop.bat` — atalhos no Windows que localizam a porta COM da Pico automaticamente e gerenciam a abertura/fechamento coordenado da janela 3D e do `tracker`.
- `requirements.txt` — dependências Python do lado PC (`pygame`, `numpy`, `pyserial`, `opencv-python`, `mss>=9.0,<10`, `matplotlib`, `dxcam`).

### Documentação e medições (`docs/`)

- `docs/arquitetura.md` — arquitetura do firmware, protocolo, controlador e síntese das medições.
- `docs/guia_codigo.md` — este documento.
- `docs/medicoes/` — arquivos CSV reais coletados na bancada com a interface Shooter 3D (`ident_telem.csv`, `step_trim.csv`, `sine_trim.csv`, `ramp_trim.csv`, `smooth_trim.csv`).
