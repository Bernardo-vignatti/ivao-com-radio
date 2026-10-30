# COM — o iPhone como painel de rádio para a IVAO

[![Licença: MIT](https://img.shields.io/badge/licen%C3%A7a-MIT-FFA524.svg)](LICENSE)
![Windows](https://img.shields.io/badge/PC-Windows%2010%2F11-293134.svg)
![MSFS](https://img.shields.io/badge/sim-MSFS%202020-293134.svg)
![Python](https://img.shields.io/badge/python-3.12%2B-293134.svg)

**[Read in English](README.md)**

O COM transforma o iPhone num rádio comm de painel para voar na rede IVAO com
o Microsoft Flight Simulator: display no estilo de descarga de gás com
frequência ativa e standby, botão de troca, botão giratório duplo, um botão
grande de PTT e a lista de ATC online por perto, ordenada por distância.
Tocar num controlador manda a frequência dele para o standby, como num rádio
de verdade.

O áudio e o microfone continuam no PC. O celular é só o painel.

<p align="center">
  <img src="docs/radio.png" width="250" alt="Tela do rádio com alguém transmitindo: moldura verde, display de sete segmentos com ativa 122.800 e standby 118.700, botão giratório, PTT verde, lista de ATC por perto">
  &nbsp;
  <img src="docs/waiting.png" width="250" alt="Tela de espera, mostrada quando o app do PC está fechado: o display do rádio apagado">
</p>
<p align="center">
  <img src="docs/pc-window.png" width="600" alt="Painel do app no PC com cards de estado, espelho do rádio, gráfico do áudio do IVAO e ATC por perto">
</p>

## O que faz

- **PTT** pelo celular, com proteção contra tecla presa: se o Wi-Fi cair com
  o botão apertado, o PC solta a tecla em 700 ms, e você nunca fica
  transmitindo sem querer.
- **Frequência ativa e standby** lidas e escritas no simulador. Troca como no
  rádio real. O standby se sintoniza pelo botão giratório duplo (anel de fora
  em MHz, miolo em kHz; um toque no miolo liga os canais de 8.33 kHz) ou pelo
  teclado numérico.
- **ATC por perto**, pelos dados públicos da IVAO, ordenado pela distância do
  seu avião. Tocar num controlador carrega a frequência no standby.
- **Indicador de recepção.** A moldura inteira da tela fica verde quando
  alguém fala e vermelha quando é você, legível pelo canto do olho com o
  celular num suporte.
- **Jeito de app.** Adicione à tela de início uma vez: abre em tela cheia e
  mostra "Aguardando o PC" até você abrir o COM no computador, e aí o rádio
  aparece sozinho.
- **Sem configurar som.** Sem cabo virtual e sem roteamento: o COM observa o
  volume do IVAO no mixer do Windows para saber quando alguém está falando.
- **Painel no PC, na bandeja do sistema.** Uma janela mostra o estado de cada
  parte, um gráfico do áudio ao vivo para ajustar o squelch, a tecla de PTT e
  todas as configurações. Fechar a janela deixa o COM rodando na bandeja; para
  sair, use o menu da bandeja.

## Como funciona

O app de pilotos da IVAO não tem API, então o COM nunca fala com a IVAO. Ele
age no PC por fora, do mesmo jeito que os addons de PTT para joystick:

| O quê | Como |
|---|---|
| PTT | Aperta a tecla que você já configurou como PTT na IVAO, pelo `SendInput` do Windows com scancode (funciona com o simulador em tela cheia) |
| Frequências | Lê e escreve o rádio COM do simulador pelo SimConnect; a IVAO segue o rádio do simulador |
| Luz de recepção | Lê o pico de volume do IVAO no mixer de áudio do Windows |
| Lista de ATC | API pública Whazzup da IVAO, a cada 15 s |

```
iPhone (app web na tela de início, guardado pelo service worker)
   │  WebSocket por HTTPS no seu Wi-Fi, com certificado local
   ▼
COM Radio.exe ── um estado só, enviado 10 vezes por segundo
   ├── ptt.py       SendInput com scancode
   ├── sim.py       SimConnect: lê rádio e posição, escreve standby e troca
   ├── audio.py     pico do IVAO no mixer do Windows, com squelch
   ├── whazzup.py   API pública da IVAO, distância por haversine
   └── certs.py     autoridade certificadora local, para o Safari aceitar HTTPS
```

O Safari só mantém um app web funcionando sem conexão em HTTPS, então o COM
cria uma pequena autoridade certificadora no seu PC. Você confia nela no
iPhone uma vez.

## Requisitos

- Windows 10 ou 11 com o Microsoft Flight Simulator 2020
- O app de pilotos da IVAO, com uma tecla de PTT configurada
- Um iPhone no mesmo Wi-Fi que o PC

## Começo rápido

1. Baixe o `COM-Radio-Setup-<versão>.exe` da
   [última release](../../releases/latest) e abra. Ele instala o COM em
   Arquivos de Programas, cria os atalhos, libera o COM nas redes
   **privadas** do Firewall do Windows (senão o iPhone não alcança o PC) e
   instala o WebView2 da Microsoft se faltar. Para desinstalar, use as
   Configurações do Windows como em qualquer programa.
   - O instalador não tem assinatura digital, então o SmartScreen do Windows
     pode avisar na primeira vez: clique em **Mais informações › Executar
     assim mesmo**.
   - O seu Wi-Fi precisa estar marcado como rede **privada** no Windows.
2. Abra o **COM Radio** pelo menu Iniciar.
3. **Defina a tecla de PTT:** na página **Tecla PTT**, clique em **Mudar
   tecla** e aperte a tecla ou o botão do mouse que você usa como PTT na IVAO.
   O COM reconhece e salva sozinho; não precisa saber o nome da tecla.
4. **No iPhone, uma vez só:** na página **iPhone**, aponte a câmera para o QR
   code (ou abra no Safari o endereço `http://…:8080` que ela mostra) e siga
   os quatro passos da página:
   1. baixe o certificado;
   2. instale em **Ajustes › Perfil Transferido**;
   3. ligue em **Ajustes › Geral › Sobre › Ajustes de Confiança de
      Certificados**;
   4. quando a página mostrar o botão verde, abra o rádio e use
      **Compartilhar › Adicionar à Tela de Início**.

Daí em diante: abra a IVAO, abra o COM, toque no ícone COM no celular e voe.

O certificado fica em `%APPDATA%\COM Radio\certs`. Não apague essa pasta: sem
ela, o PC cria outro certificado e o iPhone precisa repetir o passo 4. Ao
desinstalar, o COM pergunta antes de apagar.

Vindo da versão antiga em zip? Copie o `config.json` antigo para
`%APPDATA%\COM Radio\` antes de abrir a nova, ou só defina a tecla de novo.

## Configuração

Tudo se muda pela janela: a página **Áudio** tem os controles do squelch sobre
um gráfico ao vivo e acha o programa do IVAO para você, e **Configurações**
tem o resto, inclusive iniciar com o Windows. Fica tudo salvo em
`%APPDATA%\COM Radio\config.json`, que também dá para editar à mão (com o COM
fechado).

| Chave | Padrão | O que faz |
|---|---|---|
| `ptt_key` | `leftctrl` | Tecla apertada no PTT. O jeito fácil é o botão **Mudar tecla** da janela. À mão: letras, números, `f1` a `f24`, teclas do numpad, modificadoras (`leftctrl`, `rightalt`…) ou botões do mouse `mouseback`, `mouseforward`, `mousemiddle`. Lista completa: `SCANCODES` no `app/ptt.py` |
| `ptt_deadman_ms` | `700` | Solta o PTT se o celular ficar esse tempo sem dar sinal |
| `audio_process` | `["ivao", "altitude"]` | Qualquer pedaço do caminho do programa cujo volume quer dizer "alguém falando" |
| `squelch_open` / `squelch_close` | `0.03` / `0.01` | Nível que acende / apaga a luz de recepção |
| `squelch_hang_ms` | `350` | Segura a luz acesa nas pausas curtas da fala |
| `whazzup_radius_nm` | `250` | Até que distância procurar ATC |
| `whazzup_max_stations` | `12` | Quantos controladores listar |
| `whazzup_interval_s` | `15` | De quanto em quanto tempo pedir a lista de ATC à IVAO (no mínimo 15) |
| `port` / `setup_port` | `8443` / `8080` | Rádio (HTTPS) e página de instalação (HTTP) |
| `sim_enabled`, `audio_enabled`, `whazzup_enabled` | `true` | Desligam uma parte |
| `tray_on_close` | `true` | Fechar a janela deixa o COM rodando na bandeja |

Dicas para a tecla de PTT:

- Se o Ctrl esquerdo faz outra coisa no seu simulador, `f13` é uma boa
  escolha: nenhum programa usa.
- Com `mouseback`, a janela em foco também recebe um "voltar" de verdade.
  Dentro do simulador não faz nada, mas um navegador na frente volta uma
  página a cada transmissão.

## Segurança

Um PTT preso travaria a frequência para todo mundo, então soltar a tecla tem
cinco caminhos: o celular manda um sinal a cada 200 ms enquanto você segura o
botão e o PC solta depois de 700 ms sem sinal; o celular também solta quando
o app vai para segundo plano, quando perde o foco e quando a página fecha, e o
PC solta na desconexão e no encerramento. Com dois celulares abertos, só o
primeiro a apertar controla o PTT até soltar.

## Se algo não funcionar

**O PTT não transmite.** Clique em **Testar tecla** na página do PTT. Se ele
disser que a tecla saiu e a IVAO continuar muda, a tecla não bate com o PTT
configurado na IVAO. Erro 5 quer dizer que a IVAO ou o simulador rodam como
administrador e o COM não: abra o COM como administrador também. Com o
simulador em tela cheia exclusiva, teste em janela sem bordas.

**"MSFS fechado" com o simulador aberto.** Carregue um voo até estar no
cockpit; no menu principal o simulador não responde às variáveis do rádio.

**A frequência não muda.** Confira a energia da aviônica: o simulador ignora
escrita de rádio com a aviônica desligada. O `py app/server.py --test-sim`
escreve uma frequência, confere se entrou, troca e devolve tudo como estava.

**"Abra o IVAO para ter o indicador de RX" com o IVAO aberto.** Na página
**Áudio**, clique em **Procurar programas com som** com alguém falando na
frequência e escolha o certo em **Usar este**.

**A luz de recepção pisca ou nunca acende.** Na página **Áudio**, olhe o
gráfico quando alguém fala e arraste a linha de abrir um pouco abaixo da voz e
a de fechar mais ou menos na metade. O nível acompanha o volume do IVAO no
Windows.

**A lista de ATC fica vazia.** Aumente o raio de busca em **Configurações**.

**A janela não abre.** O COM pode já estar rodando na bandeja (abrir de novo
só mostra a janela). Se não for isso, instale o "Edge WebView2 Runtime" da
Microsoft. O registro fica em `%APPDATA%\COM Radio\com-radio.log`.

## Rodar pelo código

Precisa de Python 3.12 ou mais novo, no Windows.

```bash
py -m pip install -r requirements.txt
py app/gui.py
```

O `py app/server.py` roda o mesmo servidor num terminal, com modos de
diagnóstico:

| Comando | O que faz |
|---|---|
| `py app/server.py --doctor` | Confere PTT, áudio, dados da IVAO e simulador, e diz o que falta. **Aperta a tecla de PTT de verdade** |
| `py app/server.py --test-ptt` | Aperta e solta a tecla de PTT e confirma que o Windows viu |
| `py app/server.py --test-sim` | Escreve no standby do COM1 do simulador, troca e devolve tudo |
| `py app/server.py --list-audio` | Lista os programas tocando som, para achar o da IVAO |
| `py app/server.py --meter` | Nível de recepção ao vivo, para ajustar o squelch |
| `py app/server.py --fake-sim` | Roda com um simulador falso, para mexer na interface |

O `py app/gui.py --fake-sim` abre a janela com o simulador falso.

O `build.bat` gera o app com o PyInstaller e depois o instalador
`dist\COM-Radio-Setup-<versão>.exe` com o [Inno Setup](https://jrsoftware.org/isinfo.php)
(`winget install JRSoftware.InnoSetup`).

As duas interfaces são HTML, CSS e JavaScript puros, sem etapa de build: o
rádio do celular em `app/static/` e a janela do PC em `app/desktop/` (mostrada
pelo [pywebview](https://pywebview.flowrl.com/), que fala com o Python pela
ponte dele, nunca pela rede). A fonte é a [B612](https://b612-font.com/),
desenhada pela Airbus para displays de cockpit; os dígitos de sete segmentos
do celular são desenhados em SVG.

## Aviso

O COM é um projeto independente, sem vínculo nem aprovação da IVAO. Ele não
se conecta aos servidores da IVAO nem mexe no protocolo dela: só aperta uma
tecla, fala com o simulador pelo SimConnect e lê dados públicos.

## Licença

[MIT](LICENSE) © 2026 Bernardo Vignatti
