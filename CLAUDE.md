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
gui.py     ── janela pywebview (app/desktop/) e bandeja; vira "COM Radio.exe"
server.py  ── estado único, broadcast a 10 Hz
   ├── certs.py     CA local, certificado do servidor, página de instalação
   ├── ptt.py       SendInput com scancode
   ├── sim.py       SimConnect: lê rádio e posição, escreve standby e swap
   ├── audio.py     pico da sessão do IVAO no mixer do Windows, squelch
   └── whazzup.py   API pública da IVAO a cada 15 s, haversine
```

O celular só emite eventos. Toda decisão mora no servidor.

Pastas: o código Python, a interface do celular (`static/`) e a do PC
(`desktop/`) moram em `app/`; na raiz ficam `config.json`, `build.bat`,
`installer.iss`, `requirements.txt`, os READMEs, `assets/` (ícone e
`make_icons.py`) e `docs/` (prints). Os módulos de `app/` se importam pelo
nome (`import audio`), o que funciona porque o Python põe a pasta do script
no caminho; por isso os comandos são `py app/server.py` e `py app/gui.py`,
sem `-m`. Fora do .exe, `server.py` lê o `config.json` da pasta acima dele;
no .exe, de `%APPDATA%\COM Radio` (ver Instalador).

Portas: `8443` HTTPS com o rádio, `8080` HTTP só com a página de
instalação (`app/static/setup.html`) e o `ca.crt`.

Modos de linha de comando: `--doctor` (checa as quatro pontas e diz o que
falta), `--test-ptt`, `--test-sim` (escreve no rádio do MSFS e desfaz),
`--meter` (nível ao vivo para calibrar o squelch), `--list-audio` (quem
está tocando som e quanto, para achar o processo do IVAO),
`--fake-sim`. Esses modos só existem no `py app/server.py`: o .exe não tem
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

**A tecla se define apertando ela (out/2026).** Achar o nome certo e editar o
`config.json` era difícil para o usuário. O botão Mudar da janela do PC chama
`ptt.capture()`, que lê o `GetAsyncKeyState` global até alguma tecla descer,
e `server.set_ptt_key()`, que troca a tecla com tudo rodando e reescreve só a
linha `ptt_key` do config. Detalhes que importam:

- O mapa de captura sai do próprio `SCANCODES` pelo `MapVirtualKey`, então
  toda tecla capturável também é enviável. O numpad entra à mão
  (`VK_NUMPAD*` com Num Lock). O Enter do numpad vira `enter`: o Windows dá
  o mesmo VK aos dois.
- Global e não por eventos do tkinter: o tkinter no Windows não enxerga os
  botões laterais do mouse, e a janela nem precisa de foco. Botões esquerdo
  e direito ficam de fora (o esquerdo acabou de clicar em Mudar); tecla já
  apertada no início só conta depois de soltar.
- **Recusa trocar com PTT apertado ou com alguém segurando**, e solta a tecla
  antiga depois da troca: sem isso a tecla antiga poderia ficar presa, que é
  o que o dead-man switch existe para impedir.
- Mudar só na janela do PC, por decisão do usuário: a tecla é apertada no
  teclado do PC de qualquer jeito.

Testado com tecla real (F13, Ctrl e Shift dos dois lados, Alt), com a
recusa no meio de transmissão e com o tempo esgotando sem tecla.

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
  projeto: o .exe e o `py app/server.py` precisam da mesma CA. A `ca.key` nunca
  vai para o git nem para o celular.
- **A CA só vale para a rede local (revisão de out/2026).** Ela tem
  `NameConstraints` crítico: só `.local`, `localhost` e IPs privados. Se a
  `ca.key` vazar, ninguém assina um site de verdade que o iPhone aceite
  (testado: o OpenSSL recusa `www.google.com` assinado por ela). Por isso o
  certificado do servidor perdeu o nome curto do PC, que ficaria fora da
  restrição. CAs criadas antes continuam valendo, sem a restrição; para ganhar
  a restrição, apague a pasta `certs` e instale de novo no iPhone.
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
`server.make_server()` e roda o `uvicorn.Server` numa thread. Sair põe
`should_exit`, o que passa pelo `lifespan` e solta a tecla — o caminho do
shutdown do dead-man switch continua o mesmo. No .exe o stdout e o stderr vão
para `%APPDATA%\COM Radio\com-radio.log`: sem isso o uvicorn quebra ao
perguntar se o stdout é terminal. Porta ocupada vira uma caixa de mensagem.

**Janela do PC em pywebview (out/2026).** O tkinter não fazia o visual que o
usuário pediu (cards arredondados, gráfico, controles). A janela é HTML/CSS/JS
puro em `app/desktop/`, mostrado pelo WebView2 via pywebview (testado no
Python 3.14 com pythonnet 3.2). Detalhes que importam:

- **A página fala com o Python pela ponte `js_api` (classe `Api`), nunca pela
  rede.** Configurações e teste de tecla não podem ficar alcançáveis pelo
  Wi-Fi; o celular só enxerga o rádio. O pywebview não expõe nomes com `_`.
- **`Api.set_config` só aceita as chaves de `NUMBERS`, `SWITCHES`,
  `audio_process` e `autostart`, com limites.** O que dá para aplicar ao vivo
  (squelch, raio, intervalo, processo do IVAO) entra na hora mexendo nos
  atributos do `RX` e do `FEED`; `sim_enabled`, `audio_enabled` e
  `whazzup_enabled` valem ao reabrir. `server.save_config` troca só o valor
  da chave no arquivo, como o `set_ptt_key` sempre fez. O `ptt_deadman_ms`
  fica de fora de propósito: é o parâmetro de segurança.
- **Bandeja com pystray.** O X esconde a janela (`closing` devolve False) e o
  servidor segue; `tray_on_close: false` volta a fechar de vez. Sair pela
  bandeja ou pelo botão da janela chama `quit_app`, que destrói a janela, e o
  fim do `__main__` faz o mesmo desligamento de antes. Testado com F13
  apertada: o lifespan soltou a tecla.
- **Uma instância só**, pelo mutex `COMRadio.Instance`. Abrir de novo sinaliza
  o evento `COMRadio.Show` e a janela escondida aparece. O instalador usa o
  mesmo mutex (`AppMutex`).
- **Barra de título escura** por `DwmSetWindowAttribute(20)` no evento
  `shown`, seguida de `SetWindowPos` com `FRAMECHANGED`; sem esse segundo
  passo ela só escurece no próximo redesenho.
- **Iniciar com o Windows** grava `"<exe>" --tray` em `HKCU\...\Run`, só no
  app instalado. `--tray` abre escondido.
- A captura de tecla e o teste mantêm as recusas de antes: nada com PTT
  apertado ou com algum celular segurando. O teste pede dois cliques porque
  transmite de verdade com o Altitude conectado.

**Instalador (out/2026).** O usuário trocou o zip por um instalador. O
`build.bat` gera `dist\COM Radio\` com PyInstaller em pasta (abre mais rápido
que arquivo único e o antivírus desconfia menos) e compila `installer.iss`
com o Inno Setup (`winget install JRSoftware.InnoSetup`, por usuário). O
instalador põe tudo em Arquivos de Programas, cria atalhos, adiciona a regra
"COM Radio" no firewall só em rede **privada** (apagando antes para não
duplicar), baixa o WebView2 se faltar e, na desinstalação, tira a regra, o
`Run` e pergunta antes de apagar `%APPDATA%\COM Radio` (que tem a CA).

- **Config e log em `%APPDATA%\COM Radio`** no app instalado, porque
  Arquivos de Programas não aceita escrita. Na primeira abertura o config vem
  de um `config.json` ao lado do .exe (o zip antigo), ou do padrão empacotado.
- **Atualização pelo app.** `find_update` lê as releases do GitHub
  (pré-releases contam) ao abrir o app instalado e no botão Procurar, e pega a
  maior versão acima de `VERSION` com um `COM-Radio-Setup-*.exe` anexado.
  Instalar baixa para uma pasta nova em `%TEMP%`, com nome fixo (o nome do
  GitHub iria parar numa linha do `cmd`), exige e confere o sha256 que o
  GitHub publica no `digest` do anexo, e roda o instalador com `/SILENT` por um `cmd` que
  espera 3 s: o `AppMutex` faz o instalador recusar com o app aberto, então o
  app sai antes (pelo caminho normal, que solta a tecla). Recusa com PTT
  apertado. O `[Run]` do instalador não tem `skipifsilent` para o app
  reabrir no fim. Testado: busca, versão, hash e a tela; a troca de versão de
  ponta a ponta só dá para ver quando existir uma release acima da instalada.
- A versão mora em dois lugares: `VERSION` no `gui.py` e `AppVersion` no
  `installer.iss`. Mudou uma, muda a outra.
- Depois de mudar qualquer arquivo, rode o `build.bat` de novo.

**Dead-man switch.** O celular manda heartbeat a cada 200 ms enquanto o PTT
está apertado; 700 ms sem heartbeat e o servidor solta a tecla. Sem isso, uma
queda de Wi-Fi deixaria o usuário transmitindo indefinidamente e travaria a
frequência para todos na rede. A tecla também é liberada em
`visibilitychange`, `blur`, `pagehide`, no disconnect e no shutdown. **Essa é
a parte crítica do projeto — qualquer refatoração precisa preservar os cinco
caminhos.** Só o primeiro cliente a apertar controla o PTT até soltar.

Da revisão de out/2026, que endureceu esse caminho:

- **O dead-man roda no `guard`, separado do `pump`**, a cada 50 ms. Antes
  ele morava no laço do envio: um celular que sumia sem fechar a conexão
  podia prender o `send_text`, e um erro montando o estado matava a tarefa
  e o dead-man junto. Agora cada envio tem 1 s (`SEND_TIMEOUT`) e os dois
  laços pegam exceção sem morrer.
- **Release que falha não marca a tecla solta.** Se o `SendInput` recusa o
  keyup, `is_down` fica verdadeiro e o `guard` (`check_stuck`) tenta de novo
  até o Windows aceitar.
- **O WebSocket confere o `Origin`**: só a página do rádio (`https`, a porta
  certa, um nome do certificado). Sem isso, qualquer site aberto no Safari
  do iPhone, que confia na CA, poderia apertar o PTT. Cliente sem `Origin`
  passa: navegador sempre manda, e os testes não. Mensagens acima de 4 KB
  derrubam a conexão (`ws_max_size`).

Testado contra o servidor: origem de outro site recusada; celular travado sem
ler nada por 12 s enquanto outro transmitia, com o estado chegando e o
dead-man soltando em 0,5 s; release falho solto na volta seguinte.

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

**Celular: o rádio físico (out/2026).** O usuário pediu realismo, com o
Bendix/King KX155 como referência, só na vertical. Placa preta fosca com
parafusos e legendas brancas impressas, tudo em CSS, sem imagens. O display
imita a descarga de gás: dígitos de sete segmentos desenhados em SVG pelo
`app.js` (`buildSeg`/`setSeg`), com os segmentos apagados visíveis como
fantasma, legendas USE e STBY, e TX, RX, 8.33 e uma barra de sinal
segmentada (o nível do IVAO) no rodapé do display. Sem fonte de sete
segmentos para baixar: funciona offline. Tipografia B612 no resto.

Em cima, três lâmpadas de anunciador (PC, MSFS, ÁUDIO) substituem o antigo
rodapé de texto; a tecla de PTT em uso aparece gravada no próprio botão.

**Botão giratório duplo.** Anel de fora em MHz (118 a 136, dando a volta),
miolo em kHz, que dá a volta sem mexer no MHz, como no rádio real. 18° por
clique. Passos de 25 kHz; um toque no miolo sem girar liga os canais de 8.33
(nomes .000/.005/.010/.015 de cada bloco de 25), como puxar o miolo de um
KX155A, e fica guardado no `localStorage`. O display mostra o valor girado na
hora; o `standby` sai 450 ms depois do último clique e ao soltar, nunca a
cada clique, para não inundar o SimConnect. O valor girado fica na tela até o
simulador confirmar ou 2,5 s passarem. 136.975 é o teto: no MHz 136 o kHz
para em 975.

O teclado numérico continua (botão FREQ): girar é lento para saltos grandes.

A assinatura é a moldura da tela funcionando como anunciador: verde inteira
quando alguém transmite, vermelha quando é o usuário. O objetivo é ser legível
pelo canto do olho, com o celular num suporte, sem exigir foco. Preserve isso.
O PTT segue a mesma lógica de cor (borracha escura, verde no RX, vermelho e
afundado no TX).

Os dígitos e o botão giratório usam `clamp()` com `vw`: em largura fixa o
standby vazava para fora da tela num iPhone de 375 px.

Sem WebSocket, uma tela "Aguardando o PC" cobre tudo: o rádio aparece
desligado, só com os segmentos fantasma, e uma luz âmbar pulsando. Ela
aparece na hora quando o app abre sem servidor, e só depois de 1,5 s numa
queda, para um soluço de Wi-Fi não piscar a tela. A reconexão tenta no máximo
a cada 2 s, para o rádio aparecer logo quando o PC abre.

O botão de PTT só apaga quando o WebSocket cai. Ele não depende do MSFS — a
tecla vai para o Altitude com o simulador fechado, então apagar por causa do
simulador seria mentira. O botão giratório não responde sem WebSocket.

Erros de SimConnect e de áudio aparecem numa etiqueta de aviso acima do
rádio. Erros que o servidor devolve (frequência recusada) piscam no próprio
display por 2,5 s.

**PC.** Grafite escuro, cards de cantos arredondados, âmbar, verde e vermelho
do celular, Segoe UI no texto e B612 Mono nos números. Páginas: Painel
(estado das cinco pontas, espelho do rádio, gráfico do nível, ATC), Áudio
(gráfico grande com as linhas do squelch, controles deslizantes, procurar
programas com som), Tecla PTT, iPhone (QR e passos) e Configurações.

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
  limpo. O `py app/server.py` reaproveita a mesma CA.
- Tela de espera num navegador: aparece quando o servidor cai e some sozinha
  quando ele volta.
- Redesign de out/2026, nesta máquina: a janela pywebview abre pelo `py` e
  pelo `dist\COM Radio\COM Radio.exe` (com o config migrado para
  `%APPDATA%`); o X esconde na bandeja e abrir de novo mostra a janela; o
  Sair solta a tecla apertada pelo lifespan. As cinco páginas do PC com uma
  ponte falsa no navegador. No celular, em 375×812: o display, o botão
  giratório (MHz dando a volta, kHz em 25 e em 8.33, envio só depois de
  parar, confirmado pelo simulador falso), o PTT pela interface (moldura,
  heartbeat, blur soltando) e, contra o servidor, os cenários do PTT de novo
  (normal, dead-man, heartbeat segurando, outro cliente não solta, frequência
  fora da faixa, lixo, desconexão soltando).

**Ainda não verificado**, e só o usuário consegue fechar:

- O instalador rodando de verdade: pede administrador (UAC), então ficou para
  o usuário. Compila sem erro; falta ver a instalação, os atalhos, a regra do
  firewall, o Iniciar com o Windows pelo app instalado e a desinstalação.
- O botão giratório com o dedo num iPhone de verdade (testado com eventos de
  ponteiro sintéticos e mouse).

- O iPhone instalando a CA e confiando nela, e o service worker abrindo a
  tela de espera com o PC desligado.
- O iPhone resolvendo `<nome-do-pc>.local`. Se não resolver, a página de
  instalação cai para o IP sozinha.

- O Altitude reagindo à tecla. O servidor prova que a tecla sai; se o Altitude
  não transmitir, a tecla do `config.json` não é a mesma configurada lá.
- O iPhone numa rede Wi-Fi real. O firewall do Windows precisa liberar o
  `COM Radio.exe` (e o Python, para `py app/server.py`) na rede privada.
- **Qual processo do IVAO toca a voz.** O IVAO só abre com o MSFS aberto.
  Com os dois abertos, `py app/server.py --list-audio` mostra. Se a voz sair de
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
HTML, CSS e JS puros, editáveis direto, tanto no celular quanto no PC. Configuração vai para o
`config.json`, nunca fixa no código.

O repositório é público no GitHub (`ivao-com-radio`, licença MIT). O
`README.md` é em inglês e o `README.pt-BR.md` é a mesma coisa em português:
mudou um, muda o outro. Os prints em `docs/` saem da interface com
`--fake-sim` (o do PC com `py app/gui.py --fake-sim`). O `config.json` do
repositório tem os padrões públicos (`ptt_key` em `leftctrl`) e vai empacotado
como padrão; o do usuário mora em `%APPDATA%\COM Radio`. A release leva o
`COM-Radio-Setup-<versão>.exe` com esse nome: é por ele que o app acha a
atualização.
