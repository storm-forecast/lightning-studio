# Template oficial — Lightning Agent

Vídeo aprovado: `output/boletim-oficial.mp4`.
Manifesto dos arquivos e parâmetros: `templates/oficial.json`.
Este vídeo é a referência visual aprovada. Seus mapas são de arquivo de
30/10/2026, não uma previsão atualizada.

## Padrão aprovado

- Full HD: 1920 × 1080, 25 fps, H.264, AAC e faststart.
- Mapa inteiro à esquerda, em painel de 1440 × 810, sem cobertura da apresentadora.
- Apresentadora à direita, com recorte central e proporção preservada.
- Movimentos no ritmo original: `PRESENTER_SPEED=1.0`.
- Voz feminina brasileira Francisca: `pt-BR-FranciscaNeural`, gerada com taxa -5%.
- Narração reduzida mais 10% na montagem: `NARRATION_SPEED=0.90`.
- Boca sincronizada depois de aplicar as velocidades finais.
- Música extraída do mesmo vídeo-base, com transição suave na repetição,
  volume baixo, redução durante a fala e fades no início/fim.

## Arquivos necessários

| Arquivo | Uso |
| --- | --- |
| `apresentadora-base.mp4` | Clipe original `gemini_generated_video_7cc0f87e.mp4` |
| `fundo-musical.wav` | Música extraída com Demucs; pode conter resíduos da separação |
| `apresentadora-referencia-sincronizada.mp4` | Apresentadora sincronizada exclusivamente com a narração aprovada |
| `narracao-referencia.wav` | Narração aprovada, já na velocidade final |
| `oficial.json` | Registro da aprovação e hash SHA-256 do vídeo oficial |
| `limpeza-versoes.json` | Registro das versões de vídeo removidas |

O compositor usa o clipe e a música incluídos no projeto. Não depende dos
arquivos em Downloads. A imagem do cenário da apresentadora é decorativa;
os dados meteorológicos vêm exclusivamente do Lightning Agent.

## Gerar próximo boletim

O worker utiliza `app/official.py`: narração → velocidade final → sincronização
labial por roteiro → montagem com mapas e música. A sincronização nunca é
reutilizada com outro texto. Menus e chat são ocultados nas novas capturas;
legenda, período e atribuição dos dados são preservados.

Para gerar com mapas e narração já disponíveis, na raiz do repositório:

```bash
python scripts/render_broadcast.py --official \
  --maps caminho/mapa-1.png caminho/mapa-2.png \
  --audio caminho/narracao.wav \
  --title "Previsão de raios | Brasil" \
  --subtitle "Informe o período real de validade dos dados" \
  --output output/novo-boletim.mp4
```

A opção `--official` aplica as velocidades e a sincronização. Não misturar
com `--timing-final`, que é reservado para áudio e clipe já sincronizados.

## Execução e limites

O ambiente local de sincronização fica em `.local/venv` e `.local/Wav2Lip`,
com `checkpoints/wav2lip-compatible.pth`. `LIPSYNC_PYTHON` permite configurar
o interpretador que tem as dependências instaladas. A execução limita o
processamento a dois threads de CPU. O Docker básico inclui o template e os
scripts, mas não inclui o ambiente/modelo de sincronização: precisa ser
provisionado no worker antes de gerar o padrão oficial na nuvem. Na ausência
dele o job informa erro, sem produzir silenciosamente uma boca dessincronizada.

O modelo Wav2Lip instalado tem restrição comercial. A aprovação visual não
altera a licença do modelo. A voz online depende da disponibilidade do serviço.
Nenhum serviço pago foi contratado.

## Direção editorial e correspondência entre fala e imagem

Use o [prompt mestre](../prompts/boletim-meteorologico.md) e o
[processo de produção](../docs/processo-producao.md). Eles definem a ordem das
camadas, as distinções técnicas, até dois destaques locais e a linha do tempo
medida pelo áudio de cada cena. O worker usa cenas com áudios próprios e durações medidas. As transições
ocorrem nos limites de cada fala, sem dividir o áudio total igualmente entre mapas.

## Fonte das previsões e atribuição da IA

Todas as previsões usam exclusivamente o modelo do Centro Europeu de Previsões
Meteorológicas a Médio Prazo (ECMWF), o ECENS, inclusive chuva. Se a chuva ECENS
não estiver disponível, informar a ausência sem substituir por GFS. A previsão
de raios e suas áreas de risco são geradas pelo modelo de inteligência artificial
usando parâmetros convectivos do ECENS; não são uma saída direta de raios do
modelo meteorológico. Essa distinção aparece na fala de abertura e permanece
escrita nas cenas de previsão de raios, inclusive nos destaques locais.
`forecast_policy.py` rejeita fontes e roteiros antigos incompatíveis.

O vídeo de referência arquivado serve à estética e ao áudio do template. Para
os próximos boletins, prevalece a política ECENS/IA acima; não se reaproveitam
as previsões de fontes antigas presentes em versões históricas.

## Vestuário diário e frequência

A apresentadora usa uma das dez cores preparadas em `vestuario/catalogo.json`,
com a mesma cor em todos os vídeos do dia de referência, no fuso de Belém.
A seleção fica registrada em `vestuario.json` em cada job. O serviço foi
configurado para intervalos de duas horas (12 boletins/dia), com fila persistente
e proteção contra disparo repetido do mesmo intervalo.
Veja [vestuário e agendamento](../docs/vestuario-e-agendamento.md) para operação,
prévia das cores e requisitos de servidor ativo e armazenamento persistente.

## Correspondência da métrica de raios

Probabilidade, chances e percentuais usam a camada Probabilidade (%).
Quantidade/contagem/acumulado de raios usam Determinística. Classes de risco
usam Área de Risco. Se a fala mudar de métrica, capturar a nova camada antes
da síntese e da montagem. Se houver ambas as métricas no mesmo trecho, separar
em cenas. A validação bloqueia imagem divergente ou captura indisponível.
