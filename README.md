# Rastreador Visual de Cursor 3D em RP2040

Projeto final da disciplina de **Sistemas Microcontrolados** — UTFPR Câmpus Apucarana.  
Autores: **Gabriel Paludeto** e **Daniel Elder Kroda**.

## Sobre o projeto

O projeto implementa um sistema de rastreamento visual de cursor em malha fechada usando apenas uma **Raspberry Pi Pico (RP2040)** e um cabo micro-USB, sem nenhum circuito externo.

No computador, um aplicativo em Pygame (`host/testapp`) simula um pequeno estande de tiro 3D com um robô-alvo cujo núcleo central é magenta. Um segundo programa (`host/tracker`) captura a imagem da janela a ~60 Hz, localiza o centroide do alvo em HSV, lê a posição atual do ponteiro no Windows e envia o erro de posição pela porta serial virtual (USB CDC) para a placa. O RP2040 executa um controlador PID discreto em ponto fixo a 1 kHz com estimador de latência e, pelo mesmo cabo USB, atua como um mouse HID relativo, levando o cursor até o alvo.

> **Escopo acadêmico.** O rastreamento foi desenvolvido exclusivamente para o aplicativo de teste deste repositório (`host/testapp`), sem integração com jogos ou softwares de terceiros.

Para entender o código em detalhe, consulte:
- [`docs/guia_codigo.md`](docs/guia_codigo.md) — funcionamento geral e papel de cada arquivo do repositório.
- [`docs/arquitetura.md`](docs/arquitetura.md) — divisão entre núcleos do RP2040, USB composto, protocolo, controlador e medições de bancada.
- [`docs/Rastreador de cursor com RP2040.pdf`](docs/Rastreador%20de%20cursor%20com%20RP2040.pdf) — slides da apresentação do projeto.

## Resultados medidos em bancada

Ensaio em Raspberry Pi Pico com Windows 11, captura via `mss` a 60 Hz sobre a interface Shooter 3D, aceleração do ponteiro desligada e sensibilidade em 6/11 ($K_p = 0{,}06$, $L = 6\ \text{ms}$, $g = 1{,}25\ \text{px/contagem}$, estimador ligado). Os CSVs estão em [`docs/medicoes/`](docs/medicoes/).

| Ensaio (`hw_loop.py`) | Detecção válida | Overshoot | Acomodação (2%) | Regime / RMS | Atraso |
|---|---|---|---|---|---|
| Degrau 500 px (`step_trim.csv`) | 100% | 0,0% *(meta < 10%)* | 86 ms, máx. 97 ms *(meta < 250 ms)* | 0,9 px *(meta ≤ 2 px)* | — |
| Senoide 0,5 Hz (`sine_trim.csv`) | 100% | — | — | 31,3 px (RMS) | 47 ms |
| Rampa 300 px/s (`ramp_trim.csv`) | 100% | — | — | 14,6 px (RMS) | 48 ms |
| Aleatório suave (`smooth_trim.csv`) | 100% | — | — | 22,0 px (RMS) | 45 ms |

Em todas as fases não houve descarte de relatórios HID (`hid_drop = 0`) nem erros de protocolo (`errs = 0`).

## Como executar

Você precisa de uma Raspberry Pi Pico com cabo micro-USB de dados, Windows 10/11 e Python 3.10+.

### 1. Gravar o firmware na placa

O binário pronto está em [`firmware/prebuilt/cursor_tracker.uf2`](firmware/prebuilt/cursor_tracker.uf2):

1. Segure o botão **BOOTSEL** da Pico ao conectar o cabo USB e solte em seguida.
2. Copie `cursor_tracker.uf2` para a unidade `RPI-RP2`.
3. A placa reinicia e aparece no Windows como porta serial (`USB Serial Device (COMx)`) e mouse HID. O LED interno (GP25) pisca brevemente uma vez por segundo.

### 2. Ajustar o mouse no Windows

Em **Configurações → Bluetooth e dispositivos → Mouse → Configurações adicionais do mouse → Opções do ponteiro**:

- desmarque **"Aumentar precisão do ponteiro"**;
- deixe a velocidade no meio (**6 de 11**).

Sem isso, o sistema operacional aplica ganho não linear ao movimento do ponteiro e prejudica o controle.

### 3. Instalar as dependências Python

```powershell
cd host
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 4. Rodar com a placa conectada

Com `host\.venv` criado, os dois atalhos na pasta `host/` detectam automaticamente a porta COM da Pico (`VID:PID 1209:0001`):

- [`host/jogar_shooter3d.bat`](host/jogar_shooter3d.bat) — abre o **Shooter 3D** e inicia o `tracker` em modo automático.
- [`host/rodar_hw_loop.bat`](host/rodar_hw_loop.bat) — executa o ensaio completo de identificação e trajetórias (`tests/hw_loop.py`).

Por segurança, a placa sempre inicia com a saída HID desabilitada. Dê uma **pressão curta no botão BOOTSEL** para habilitar o movimento do cursor; segurar o botão por **1 s** aciona a parada de emergência. Mantenha a janela do Shooter 3D descoberta na tela.

Se preferir rodar manualmente em dois terminais (trocando `COM5` pela porta da sua placa):

```powershell
# Terminal 1 — janela do Shooter 3D
python -m testapp --mode shooter

# Terminal 2 — rastreador e comunicação serial
python -m tracker --port COM5 --mode auto
```

**Controles na janela do `testapp`:** `1`–`4` trajetórias de ensaio (degrau, rampa, senoide, aleatório), `5` modo Shooter 3D (HP e respawn), `Clique`/`Espaço` atirar, `F` auto-fire ao travar no alvo, `V` alterna visual 3D/2D clássico (`--classic`), `ESC` sair.

**Controles no terminal do `tracker`:** `0`/`1`/`2` modo (DESLIGADO / AUTOMÁTICO / IDENTIFICAÇÃO), `k i d l z g f` seleciona parâmetro ($K_p$, $K_i$, $K_d$, $L$, zona morta, ganho, filtro D), `+`/`-` ajusta, `e` liga/desliga estimador, `s`/`o` salva/carrega na flash, `q` sair.

## Compilação do firmware e testes

Para recompilar o `.uf2` a partir do código-fonte (Pico SDK 2.x com `tinyusb`, CMake ≥ 3.13, Ninja e `arm-none-eabi-gcc`):

```powershell
set PICO_SDK_PATH=C:\caminho\para\pico-sdk
cd firmware
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build
```

Testes disponíveis:

```powershell
# Testes do software no PC (protocolo, detecção HSV na cena 3D, trajetórias e análise)
cd host
python tests/test_host.py

# Verificação da placa em bancada sem mover o cursor (1 ms, failsafe e flash)
python tests/hw_check.py COM5

# Testes unitários em C do firmware compilado no PC (requer gcc)
cd tests
make -f tests.mk test
```

## Limitações conhecidas

- Em alvos contínuos (senoide, rampa e aleatório), permanece um atraso de 45–48 ms originado na captura e detecção de imagem, que o estimador interno não compensa.
- O ganho da planta e a latência variam conforme o PC e a configuração de vídeo; ao trocar de máquina, vale repetir a identificação (`hw_loop.py`).
- As medições físicas com osciloscópio nos pinos de depuração (`GP2` e `GP3`) ainda não foram realizadas.
- O passo de controle usa alarme de hardware livre (sem sincronização por USB SOF), e o `VID:PID 1209:0001` é reservado para testes didáticos em bancada.
