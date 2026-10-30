# Processo salvo — boletim com fala e imagem correspondentes

## Entradas e referências

- Prompt operacional: `prompts/boletim-meteorologico.md`.
- Briefing recebido: `prompts/briefing-original.txt`.
- Padrão visual e sonoro: `templates/apresentacao-base.md`.
- Vídeo de referência aprovado: `output/boletim-oficial.mp4`.
- Dados novos: agente, API e visualizações oficiais do Lightning Agent.

O vídeo aprovado define a estética. Seus mapas arquivados não devem ser usados
como se fossem os dados do próximo boletim.

## Etapas

1. **Consultar os produtos.** Registrar fonte, unidade, validade, horário de
   observação e disponibilidade. Verificar a existência do produto específico
   de extrapolação de raios e o horizonte efetivamente suportado.
2. **Planejar as cenas.** Seguir chuva prevista → raios ECENS → áreas de risco →
   até dois destaques brasileiros → Nowcasting → alagamento → extrapolação →
   recomendações. Associar cada ID ao texto, ao produto e às evidências.
3. **Preparar a navegação.** Conferir os controles reais da interface. Não
   confundir botão de raios observados com raios determinísticos ECENS.
   Localizar pontos pelo mecanismo suportado pelo agente/página.
4. **Capturar cada cena.** Selecionar a camada, aguardar dados/tiles e término
   dos movimentos, confirmar fonte e período, fechar menus e capturar. Preservar
   legenda e créditos. Não confiar apenas em uma espera fixa de alguns segundos:
   verificar o estado de carregamento e a presença do conteúdo esperado.
5. **Gerar os áudios separados.** Um arquivo por cena, com voz Francisca e
   velocidade final aprovada. Não distribuir um texto único sobre mapas com
   durações iguais. Corrigir pronúncia antes da sincronização labial.
6. **Calcular a linha do tempo.** Medir cada áudio com FFprobe. Para a cena i:
   `inicio[i] = soma(duracoes anteriores)` e `fim[i] = inicio[i] + duracao[i]`.
   Se houver silêncio editorial, incluí-lo no áudio e nessa medição. Para
   animação de extrapolação, vincular cada quadro ao horizonte anunciado.
7. **Sincronizar a apresentadora.** Manter a velocidade natural do vídeo-base.
   Aplicar a redução da narração antes da sincronização. Usar exatamente essa
   faixa final na boca e na montagem. Pode-se concatenar os áudios finais na
   ordem das cenas antes de sincronizar os lábios, preservando seus limites.
8. **Montar.** Exibir o mapa correto durante todo o trecho correspondente.
   Cortar ou fazer uma transição curta em pausas entre frases, sem alterar
   as durações já contabilizadas. Manter música baixa com redução durante a voz.
9. **Revisar.** Conferir o início, meio e fim de cada cena; nomes citados,
   fenômeno, fonte e validade devem coincidir com o visual. Rever especialmente
   as passagens previsão → observação e observação → extrapolação. Conferir
   presença dos polígonos, legendas legíveis e ausência de radar/controles.
10. **Exportar e guardar.** Salvar vídeo, roteiro, plano, evidências/metadados,
    áudios por cena e relatório de revisão em um diretório identificado por job.
    Conferir duração total, integridade do MP4 e níveis de voz/música. Nunca
    sobrescrever a referência oficial durante uma geração experimental.

## Registro por job

Guardar pelo menos:

- `roteiro.md`: texto final identificado por cena.
- `plano-cenas.json`: cena, produto, fonte, validade, evidência, local, ações,
  arquivo visual, arquivo de áudio, duração medida, início, fim e disponibilidade.
- `evidencias.json`: respostas/metadados que sustentam as afirmações, sem segredos.
- `cenas/` e `audios/`: arquivos identificados pelos mesmos IDs do plano.
- `revisao.md`: alterações, ausências de dados e resultado da conferência.
- `boletim.mp4`: exportação final daquele job.

Esses nomes são o contrato de organização a implementar; não indicam que um
novo boletim ou seus arquivos já foram gerados.

## Critérios para aprovar

Cada frase que menciona chuva, raios ou risco aparece sobre a camada compatível,
na localização e no período corretos. Nenhuma frase termina depois de sua cena
ter sido substituída. Nenhuma observação é anunciada como previsão ECENS.
Alagamento potencial e extrapolação são explicitamente apresentados como tal.
A música não disputa atenção com a voz, os lábios seguem a faixa final e os
movimentos do mapa não interrompem a compreensão. Ausências são declaradas.

## Implementação atual

`app/production.py` executa a sequência do prompt e salva as evidências,
capturas, áudios e linha do tempo por job. `app/directed_scenes.py` seleciona
explicitamente chuva, ECENS, risco, locais, monitoramento e extrapolação, sem
ativar a camada de radar. As imagens são verificadas pelo estado real de
carregamento, fonte, camada e horizonte; falhas viram quadros de indisponibilidade.

`app/segments.py` mede os áudios finais, alinha os limites a quadros de 25 fps e
concatena a narração. `app/broadcast.py` recebe as durações individuais e rejeita
linhas do tempo incompatíveis. O worker utiliza esse fluxo em vez da pauta antiga
concatenada e da divisão uniforme. A CLI genérica ainda permite duração uniforme
para usos manuais, mas o boletim dirigido sempre fornece os tempos medidos.

Mensagens de limite de consultas ou erro do agente não são aceitas como fala.
Respostas meteorológicas ainda exigem revisão editorial: a disponibilidade de
uma captura não comprova todas as afirmações que um agente possa gerar.
Nesta geração, `roteiro-revisado.json` e `revisao-editorial.md` registram as
correções antes da síntese. Os dados do agente e capturas permanecem auditáveis.

A execução local é retomável por diretório. Não reutilizar texto, áudio ou
capturas de outro dia como se fossem um novo boletim: para atualização, usar
outro diretório de job.

```bash
.local/venv/bin/python \
  scripts/produce_bulletin.py \
  --directory output/novo-boletim
```

O ambiente labial deve estar instalado no worker; o Docker básico não inclui o
modelo. Mantêm-se as restrições de licença documentadas no template.

## Fonte das previsões e atribuição da IA

Todas as previsões usam exclusivamente ECENS, inclusive chuva. Se a chuva ECENS
não estiver disponível, informar a ausência sem substituir por GFS. A previsão
de raios e suas áreas de risco são geradas pelo modelo de inteligência artificial
usando parâmetros convectivos do ECENS; não são uma saída direta de raios do
modelo meteorológico. Essa distinção aparece na fala de abertura e permanece
escrita nas cenas de previsão de raios, inclusive nos destaques locais.
`forecast_policy.py` rejeita fontes e roteiros antigos incompatíveis.

## Correspondência da métrica de raios

Probabilidade, chances e percentuais usam a camada Probabilidade (%).
Quantidade/contagem/acumulado de raios usam Determinística. Classes de risco
usam Área de Risco. Se a fala mudar de métrica, capturar a nova camada antes
da síntese e da montagem. Se houver ambas as métricas no mesmo trecho, separar
em cenas. A validação bloqueia imagem divergente ou captura indisponível.
