# Shorts de alerta nowcasting — Lightning Studio

A implementação pertence ao Studio. Os dados de raios e nowcasting vêm da
API `LIGHTNING_API_URL`, por HTTP; o radar é consultado pelo adaptador
`shorts_rain.py`. Não depende de importar módulos do checkout Lightning Agent.

São monitoradas somente Rio de Janeiro, Salvador, Florianópolis, Maceió,
Gramado, São Paulo, Curitiba e Porto Alegre. Gatilhos: raios até 40 km nos
últimos 30 min, tendência de aproximação, risco alto atual ou projetado em
até 30 min e chuva forte no radar no centro da cidade. Dados vencidos são
bloqueados; ausência de dados não significa tempo seguro.

## Uso local

Com as dependências de requirements.txt, FFmpeg e fontes DejaVu instalados:

```bash
.local/venv/bin/python scripts/generate_short.py --city curitiba --directory output/short-curitiba
```

Usa dados reais. Sem gatilho, não gera vídeo; não existe forçagem de alerta
falso. Nunca publica no YouTube. Produz `short.mp4`, `voz.mp3`, quadros e
`alerta.json`. Narração Edge TTS requer rede. O vídeo é vertical 720×1280,
até 60 segundos, com mapas de coordenadas, centro e recomendações.

## API e monitoramento

No ambiente do **Studio**, configure `VIDEO_ENGINE_TOKEN` e, para monitorar
continuamente, `SHORTS_MONITOR_ENABLED=true`. O padrão é desligado.
`SHORTS_OUTPUT_DIR` pode apontar para volume persistente; por padrão usa
`VIDEO_OUTPUT_DIR/shorts`. Reiniciar sem disco persistente perde o histórico.
Habilite somente em um worker com recursos para renderização, uma instância.

Todas as rotas exigem cabeçalho `X-Video-Token`:

- GET `/v1/shorts/cidades`: lista permitida.
- POST `/v1/shorts/verificar`: consulta todas as cidades e agenda os alertas.
- GET `/v1/shorts/{id}`: andamento e evidências.
- GET `/v1/shorts/{id}/video`: download autenticado do MP4 concluído.

O monitor verifica a cada cinco minutos. Um vídeo por cidade por hora,
sem duplicar trabalho pendente. Vídeos na fila são reavaliados antes da geração.
Direção só é narrada quando existe estimativa. Mapas são recortes locais dos
produtos reais; não há identificação automática de bairros. Risco alto é
estimativa de tempestade, não confirmação de granizo ou rajadas. Chuva é
medida no ponto central, não em todos os bairros.

A publicação de Shorts no YouTube está conectada: SHORTS_AUTO_PUBLISH=true habilita upload após geração, com SHORTS_YOUTUBE_PRIVACY=public. Alertas com mais de 15 minutos são recusados. Resultados e erros ficam no campo youtube do trabalho e em youtube-short.json quando há sucesso. O monitor não
altera a geração ou publicação dos boletins completos. Deploy e ativação em
produção precisam ser realizados separadamente.

Os Shorts agora incluem a apresentadora com sincronização labial Wav2Lip,
identidade TROVOX TEMPO, horário de Brasília e cartão de risco atual/+30 min.
Requerem o mesmo modelo local dos boletins completos.

Mapas regionais agora usam tiles OpenStreetMap com atribuição visível, cache
local de sete dias e recortes pequenos por cidade. Falha do mapa interrompe
a renderização em vez de produzir fundo sem geografia. Confira a política
do provedor antes de ampliar a operação.

Worker local independente: `.local/venv/bin/python scripts/monitor_shorts.py`.
O mesmo diretório usa trava de processo para evitar dois monitores simultâneos.
O worker só funciona enquanto o computador e o processo estiverem ligados.
Ativação local não configura nem publica código no Render/GitHub.

Atualização: 13 cidades, incluindo Santa Maria (RS), Brasília, Belo Horizonte,
Campo Grande e Manaus. No máximo um aviso por cidade por dia civil local
(Manaus/Campo Grande nos próprios fusos), com histórico persistido.
Somente aproximação de atividade elétrica ou de ecos de chuva forte dispara
o aviso. Presença de raios, chuva no centro ou risco alto isolados não bastam.
Radar exige três quadros com distância de ecos fortes diminuindo; é tendência
regional, não trajetória garantida de uma célula. Falhas podem ser tentadas
novamente; trabalhos pendentes bloqueiam duplicatas.

## Operação no GitHub com computador desligado

Workflow `.github/workflows/monitor-shorts.yml`: a cada 30 minutos
(minutos 07 e 37), consulta as 13 cidades. Instala Wav2Lip somente com gatilho,
reavalia antes de renderizar e publica no canal. Usa os mesmos Secrets
YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN e
WAV2LIP_CHECKPOINT_URL dos boletins. O canal usa a variável YOUTUBE_CHANNEL_ID.
Histórico SQLite é restaurado do último artefato city-shorts-state e salvo
mesmo quando há falha, com retenção de sete dias. Concorrência serializada.
Agendamentos do GitHub podem atrasar. Não é execução de precisão.
O workflow precisa estar na branch padrão do repositório para agendar.
Não habilite simultaneamente o monitor local ou Render com outro histórico.

Córdoba, Argentina, é o 14º local monitorado e o único com idioma es-AR:
voz argentina, narração, telas, título e descrição em espanhol e horário
America/Argentina/Cordoba. Os 13 locais brasileiros permanecem em português.
O arquivo templates/shorts-publications.json registra o teste manual para
impedir outro envio automático no mesmo dia. Nos demais dias vale o SQLite.

Expansão em espanhol: Buenos Aires, Santa Cruz de la Sierra, Santiago, Bogotá,
Guayaquil, Asunción, Lima, Montevideo e Caracas, mantendo Córdoba.
Total: 23 cidades (13 em português e 10 em espanhol). Cada cidade estrangeira
usa seu fuso IANA, inclusive mudanças sazonais, e limite diário no horário local.
Narração e metadados identificam o país correto, sem referências fixas à Argentina.
