# CLAUDE.md — contexto do projeto

Documento de handoff. Leia antes de mexer em qualquer arquivo.

## O que é

Servidor local em Python que transforma um iPhone num painel de rádio para o
IVAO Altitude, usado junto com o MSFS2020. O telefone mostra frequência ativa
e standby, a lista de ATC online por distância, e tem um botão grande de PTT.

**O áudio e o microfone ficam inteiramente no PC.** O celular é só interface.
Essa decisão é do usuário e simplifica muita coisa — não a reverta sem ele
pedir explicitamente.

## Restrição central

O IVAO Altitude não expõe API nenhuma. Sem WebSocket, sem SDK de voz, sem
plugin oficial. Tudo o que este projeto faz passa por fora, pelo sistema
operacional:

- **PTT** — simula a tecla que o usuário configurou no Altitude
- **Frequência** — escreve no simulador via SimConnect; o Altitude segue o
  rádio do MSFS
- **Indicador de RX** — mede o nível de áudio que o Altitude está tocando

Nada disso toca no protocolo da IVAO, o que mantém o projeto dentro do que a
comunidade já faz abertamente (os addons de joystick PTT no flightsim.to e no
x-plane.org funcionam pela mesma via). Se em algum momento a solução parecer
exigir falar com os servidores da IVAO diretamente, pare e reconsidere.

## Arquitetura

```
iPhone (PWA na tela de início, interface guardada pelo service worker)
   │  wss://<nome-do-pc>.local:8443, LAN, CA própria
   ▼
gui.py     ── janela de status; é o que vira "COM Radio.exe"
server.py  ── estado único, broadcast a 10 Hz
   ├── certs.py     CA local, certificado do servidor, página de instalação
   ├── ptt.py       SendInput com scancode
   ├── sim.py       SimConnect: lê rádio e posição, escreve standby e swap
   ├── audio.py     pico da sessão do IVAO no mixer do Windows, squelch
   └── whazzup.py   API pública da IVAO a cada 15 s, haversine
```

O celular só emite eventos. Toda decisão mora no servidor.

Portas: `8443` HTTPS com o rádio, `8080` HTTP só com a página de
instalação (`static/setup.html`) e o `ca.crt`.

Modos de linha de comando: `--doctor` (checa as quatro pontas e diz o que
falta), `--test-ptt`, `--test-sim` (escreve no rádio do MSFS e desfaz),
`--meter` (nível ao vivo para calibrar o squelch), `--list-audio` (quem
está tocando som e quanto, para achar o processo do IVAO),
`--fake-sim`. Esses modos só existem no `py server.py`: o .exe não tem
console.

## Decisões e o porquê

**Scancode em vez de virtual key.** O MSFS em tela cheia usa DirectInput, que
ignora eventos de virtual key. `KEYEVENTF_SCANCODE` resolve. O hook do
Altitude é global, então captura mesmo com o simulador em foco.

**As structs do SendInput precisam bater byte a byte.** Em x64 o `INPUT` tem
40 bytes: `DWORD type`, 4 de padding e uma union de 32 dominada pelo
`MOUSEINPUT`. Uma versão anterior declarava a union como 24 bytes; o
`SendInput` devolvia erro 87 e não enviava nada, em silêncio — o PTT nunca
funcionou. Se mexer em `ptt.py`, confira `ctypes.sizeof(_INPUT) == 40`.
`PttKey.self_test()` aperta a tecla e confere pelo `GetAsyncKeyState`, o que
separa "o servidor não mandou" de "o Altitude não escuta essa tecla".

**Botões de mouse passam pelo mesmo SendInput.** O `mouseback` (o botão de
voltar página, `XBUTTON1`) e companhia não são scancode: vão pelo
`MOUSEINPUT` da mesma union, com `MOUSEEVENTF_XDOWN` e `mouseData`. Saiu de
graça porque a union já estava declarada inteira para a struct ter 40 bytes.
Cuidado ao sugerir: um `XBUTTON1` sintético faz o app em foco voltar de
página, então fora do simulador ele atrapalha.

**O self-test não roda no boot, de propósito.** Ele aperta a tecla de
verdade; com o Altitude conectado isso é uma transmissão curta na frequência.
Fica só nos comandos explícitos.

**O simulador é a fonte da verdade da frequência.** Escrever no Altitude
direto não é possível. `COM_STBY_RADIO_SET_HZ` mais `COM1_RADIO_SWAP`. A
variante `_HZ` é obrigatória: o `COM_STBY_RADIO_SET` antigo usa BCD16 e não
representa canais de 8.33 kHz. Como esses nomes variam entre versões do MSFS,
`sim.py` guarda a standby pedida e reclama se ela não aparecer em 2 s —
escrita que não pegou fica visível em vez de silenciosa.

**Os Request do SimConnect são montados na mão.** O `AircraftRequests` do
pacote Python-SimConnect guarda um único `Request` por nome de variável e
troca o índice nele a cada chamada. Pedir `COM_ACTIVE_FREQUENCY:1` e depois
`:2` força um `redefine()` por leitura e devolve valor do índice errado. Por
isso `sim.py` cria um `Request` por variável, com o índice já fixo.

**"Conectado" significa dado chegando.** O `SimConnect.dll` abre a conexão com
o MSFS fechado e só depois falha em toda definição de dado. Se `connected`
fosse o handle, o celular anunciaria "MSFS conectado" com o jogo fechado. A
prova de vida é ter lido alguma variável; sem dado por 12 s, derruba e reabre.

**RX medido pelo mixer do Windows, sem VB-Cable (out/2026).** O usuário quis
abrir o IVAO, abrir o COM e voar, sem configurar som. `audio.py` lê o
`IAudioMeterInformation` da sessão de áudio do IVAO — a barrinha do Mixer de
Volume — com `pycaw`, a 50 Hz. Não captura áudio: o IVAO toca direto no
headset, e o servidor caindo não deixa ninguém surdo. Squelch com histerese
(`squelch_open`, `squelch_close`, `squelch_hang_ms`) sobre o pico.

- **Não é captura por processo** porque o *process loopback* do WASAPI só
  existe do Windows 11 (build 20348) em diante, e a máquina é Windows 10
  19045. O medidor por sessão existe no 10 e basta para RX.
- **Acha o IVAO pelo caminho do exe**, não pelo nome: `audio_process` no
  config, padrão `["ivao", "altitude"]`, casa com qualquer pedaço do caminho.
  Varre todas as saídas ativas, não só a padrão, e procura de novo a cada
  2 s, porque o IVAO abre depois do servidor. Medidor que dá erro (IVAO
  fechou, headset desligou) força nova busca na hora.
- **O valor é pico, não RMS**, e já sai escalado pelo volume do aplicativo no
  Windows (tom de 0.1 mede 0.071 nesta máquina). Por isso os limites de
  fábrica são 0.03/0.01 e a barra do celular usa `sqrt(level) * 130`.
- IVAO fechado é estado normal antes do voo: `running` falso e um aviso em
  `error`, âmbar na janela do PC.

O VB-Cable, o passthrough duplex, a escolha de host API e o supervisor do
PortAudio saíram junto; estão no histórico do git antes desta mudança.
`--meter` ainda mostra relógio e um caractere girando: uma linha de zeros
parada era indistinguível de um travamento.

**HTTPS com CA própria (decisão do usuário, out/2026).** O projeto nasceu
sem HTTPS para não instalar CA no iPhone. O usuário quis que o ícone na tela
de início abra uma tela de "Aguardando o PC" mesmo com o PC desligado, e isso
só existe com a página guardada no celular, ou seja, service worker, que o
Safari só aceita em HTTPS. Hospedar a página fora (GitHub Pages) não serve:
página HTTPS não pode abrir `ws://` na LAN. Por isso `certs.py` gera uma CA
uma vez, sem mkcert, com o pacote `cryptography`.

- **A CA nunca muda.** Reinstalar no iPhone é o passo caro. Só o certificado
  do servidor se refaz, quando o IP muda ou faltam 30 dias para vencer, e o
  celular não percebe.
- **Validade de 397 dias no certificado do servidor**: a Apple recusa mais de
  825 mesmo com CA instalada à mão. Tem `serverAuth` e SAN, que o iOS exige.
- **Os certificados moram em `%APPDATA%\COM Radio\certs`**, não na pasta do
  projeto: o .exe e o `py server.py` precisam da mesma CA. A `ca.key` nunca
  vai para o git nem para o celular.
- **Nome antes do IP.** O certificado vale para `<nome-do-pc>.local` e para o IP.
  A página de instalação testa os dois de verdade pelo iPhone e manda
  instalar pelo nome se ele resolver, porque o app salvo pelo nome sobrevive
  à troca de IP. A origem salva no iPhone é o endereço: mudou o endereço,
  precisa adicionar à tela de início de novo.
- **O service worker serve do cache primeiro** e atualiza por trás. Com o PC
  desligado o fetch pela rede pode demorar dezenas de segundos até desistir;
  a tela de espera tem que aparecer na hora. Mudança no front entra na
  segunda abertura; para forçar, troque `CACHE` em `sw.js`.

**O .exe é a janela, o servidor roda numa thread.** `gui.py` chama
`server.make_server()` e roda o `uvicorn.Server` numa thread. Fechar a janela
põe `should_exit`, o que passa pelo `lifespan` e solta a tecla — o caminho do
shutdown do dead-man switch continua o mesmo. No .exe o stdout e o stderr vão
para `com-radio.log` ao lado dele: sem isso o uvicorn quebra ao perguntar se
o stdout é terminal. Porta ocupada vira uma caixa de mensagem dizendo que o
app provavelmente já está aberto. `build.bat` gera `dist\COM Radio.exe` com
PyInstaller em arquivo único e copia o `config.json` para o lado dele, sem
sobrescrever. Depois de mudar qualquer arquivo, rode o `build.bat` de novo.

**Dead-man switch.** O celular manda heartbeat a cada 200 ms enquanto o PTT
está apertado; 700 ms sem heartbeat e o servidor solta a tecla. Sem isso, uma
queda de Wi-Fi deixaria o usuário transmitindo indefinidamente e travaria a
frequência para todos na rede. A tecla também é liberada em
`visibilitychange`, `blur`, `pagehide`, no disconnect e no shutdown. **Essa é
a parte crítica do projeto — qualquer refatoração precisa preservar os cinco
caminhos.** Só o primeiro cliente a apertar controla o PTT até soltar.

## Protocolo do WebSocket

Celular para servidor:

```json
{"type": "ptt", "down": true}
{"type": "beat"}
{"type": "standby", "com": 1, "mhz": 118.7}
{"type": "swap", "com": 1}
```

Servidor para celular, a 10 Hz:

```json
{"type": "state", "sim": {"connected": bool, "callsign": str|null,
 "error": str|null, "com1": {"active": float, "standby": float},
 "com2": {...}}, "rx": bool, "level": float, "audio": bool,
 "audio_error": str|null, "tx": bool, "ptt_key": str, "atc": [...],
 "atc_error": null}
```

Validação de frequência acontece nos dois lados: 118.000 a 136.975. Mensagem
malformada é ignorada sem derrubar a conexão.

## Interface

Ancorada no objeto real, um rádio comm de painel. Frequências em âmbar sobre
preto, como o display de descarga de gás de um Bendix/King KX155. Tipografia
B612, desenhada pela Airbus para displays de cockpit, com B612 Mono nos
números.

A assinatura é a moldura da tela funcionando como anunciador: verde inteira
quando alguém transmite, vermelha quando é o usuário. O objetivo é ser legível
pelo canto do olho, com o celular num suporte, sem exigir foco. Preserve isso.

Os corpos das frequências e o botão de troca usam `clamp()` com `vw`: em
largura fixa o standby vazava para fora da tela num iPhone de 375 px.

Sem WebSocket, uma tela "Aguardando o PC" cobre tudo, com uma luz âmbar
pulsando. Ela aparece na hora quando o app abre sem servidor, e só depois de
1,5 s numa queda, para um soluço de Wi-Fi não piscar a tela. A reconexão
tenta no máximo a cada 2 s, para o rádio aparecer logo quando o PC abre.

O botão de PTT só apaga quando o WebSocket cai. Ele não depende do MSFS — a
tecla vai para o Altitude com o simulador fechado, então apagar por causa do
simulador seria mentira.

Erros de SimConnect e de áudio aparecem numa faixa acima do rádio, e o rodapé
mostra a tecla de PTT em uso. Uma barra fina embaixo das frequências mostra o
nível de áudio do IVAO, para conferir de longe que o RX está sendo medido.

Especificidades de iOS já tratadas: `-webkit-touch-callout: none` (segurar o
PTT ia abrir o menu de seleção), `setPointerCapture`, `viewport-fit=cover` com
`safe-area-inset`, Wake Lock reativado no `visibilitychange`, e
`apple-mobile-web-app-capable` para rodar em tela cheia quando adicionado à
tela de início.

Standby com botão de troca em vez de digitar direto na ativa: é como o rádio
real funciona e evita cortar uma comunicação no meio por erro de digitação.
Tocar num ATC da lista carrega no standby, não sintoniza na hora.

## Ambiente do usuário

Windows 10, Python 3.14 (chamado por `py`, não por `python`), MSFS2020,
iPhone, headset sem fio. O VB-Cable continua instalado mas
não é mais usado. Tem VPN e placa virtual do Hyper-V além da rede de
verdade; o `lan_ip()` acha o IP certo por seguir a rota padrão. Detalhes da
máquina (pasta, nome do PC, IP) ficam na memória local do Claude, não aqui:
o repositório é público. Ele não é programador
experiente — prefira instruções de terminal completas a descrições do que
fazer, e explique erros em vez de só entregar o comando.

## Verificado e não verificado

Testado nesta máquina, com o código atual:

- `SendInput` de verdade: `self_test` aperta e solta, confirmado pelo
  `GetAsyncKeyState`, em `leftctrl`, `rightalt`, `f13`, `a` e `space`, e nos
  botões de mouse `mouseback`, `mouseforward` e `mousemiddle`. As teclas do
  numpad dependem do Num Lock ligado.
- **SimConnect com o MSFS aberto, leitura e escrita.** `COM_ACTIVE_FREQUENCY`
  e `COM_STANDBY_FREQUENCY` chegam em MHz, `ATC_ID` traz o callsign. A escrita
  com `COM_STBY_RADIO_SET_HZ` e o `COM1_RADIO_SWAP` foram confirmados por
  leitura de volta, com restauração do valor original — é o que `--test-sim`
  faz. Isso era a maior incógnita do projeto e não é mais.
- Medidor por sessão: um processo Python tocando tom de 0.1 no headset foi
  achado pelo caminho do exe, mediu 0.071, abriu o squelch e fechou no
  silêncio dentro do hang. Funciona também dentro do .exe.
- Whazzup ao vivo: parsing, haversine, filtro por raio e ordenação, conferidos
  contra a resposta real da `api.ivao.aero`.
- Protocolo do WebSocket contra o servidor rodando: standby, swap, recusa de
  frequência fora da faixa, mensagem malformada, e os seis cenários do PTT
  (normal, dead-man por falta de heartbeat, heartbeat segurando a tecla, dois
  clientes disputando, cliente soltando o PTT alheio, desconexão segurando).
- Interface no viewport de 375 px: teclado numérico, validação, swap, lista de
  ATC, faixa de erro, barra de nível e a moldura anunciadora.

- O .exe gerado pelo `build.bat`: abre a janela, gera a CA em `%APPDATA%`,
  serve HTTPS pelo IP e pelo `<nome-do-pc>.local` (resolvido no próprio PC), a
  página de instalação, `wss` com estado real e 12 ATC da Whazzup, e fecha
  limpo. O `py server.py` reaproveita a mesma CA.
- Tela de espera num navegador: aparece quando o servidor cai e some sozinha
  quando ele volta.

**Ainda não verificado**, e só o usuário consegue fechar:

- O iPhone instalando a CA e confiando nela, e o service worker abrindo a
  tela de espera com o PC desligado.
- O iPhone resolvendo `<nome-do-pc>.local`. Se não resolver, a página de
  instalação cai para o IP sozinha.

- O Altitude reagindo à tecla. O servidor prova que a tecla sai; se o Altitude
  não transmitir, a tecla do `config.json` não é a mesma configurada lá.
- O iPhone numa rede Wi-Fi real. O firewall do Windows precisa liberar o
  `COM Radio.exe` (e o Python, para `py server.py`) na rede privada.
- **Qual processo do IVAO toca a voz.** O IVAO só abre com o MSFS aberto.
  Com os dois abertos, `py server.py --list-audio` mostra. Se a voz sair de
  dentro do `FlightSimulator.exe`, o medidor por sessão mistura motor e vento
  e não serve: aí a volta é o VB-Cable, que está no histórico do git.
- Os limites de fábrica do squelch (0.03 e 0.01) com voz de verdade.
- O usuário precisa desfazer uma vez a rota do IVAO para o `CABLE Input` no
  Volume do aplicativo do Windows, senão ele não ouve nada.

## Próximos passos possíveis

Nada disso foi pedido ainda. Não implemente sem o usuário pedir.

- COM2 na interface (o backend já lê e escreve)
- Botões de transponder, ident e modo
- Texto do ATIS, que já vem na resposta da Whazzup
- Salvar frequências favoritas

## Convenções

Código e comentários em português sem acentos. Mensagens de log e textos de
interface em português normal, com acento. Front sem framework e sem build:
HTML, CSS e JS puros, editáveis direto. Configuração vai para o
`config.json`, nunca fixa no código.

O repositório é público no GitHub (`ivao-com-radio`, licença MIT). O
`README.md` é em inglês e o `README.pt-BR.md` é a mesma coisa em português:
mudou um, muda o outro. Os prints em `docs/` saem da interface com
`--fake-sim`. O `config.json` do repositório tem os padrões públicos
(`ptt_key` em `leftctrl`); o do usuário mora em `dist/` e o `build.bat`
não sobrescreve. A release leva um zip com o .exe e o `config.json`.
