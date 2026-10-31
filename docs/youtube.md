# Publicação automática no YouTube

Canal de destino: `UCOrGMudYslWWWmpW8pu3UDg`.

O workflow `generate-video.yml` envia `boletim.mp4` logo após a geração.
O vídeo vai para o canal da conta que autorizou o OAuth; antes de cada envio,
o script confere que esse canal é `YOUTUBE_CHANNEL_ID` e recusa outro canal.

## Configurar uma vez

1. No Google Cloud Console, criar um projeto e ativar a **YouTube Data API v3**.
2. Em *Tela de consentimento OAuth*, tipo Externo, adicionar a conta do canal
   como usuário de teste.
3. Em *Credenciais*, criar um **ID do cliente OAuth** do tipo
   *App para computador* e baixar o JSON.
4. Localmente, logado com a conta dona do canal:

   ```bash
   python scripts/youtube_authorize.py --client-secret client_secret.json
   ```

   O script confirma o canal autorizado e mostra o refresh token. Não versionar
   o JSON nem o token.
5. Em *Settings → Secrets and variables → Actions* do repositório:
   - secrets `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`;
   - variável opcional `YOUTUBE_PRIVACY` (`private`, `unlisted` ou `public`;
     padrão `private`);
   - variável opcional `YOUTUBE_CHANNEL_ID` para trocar o canal.

Sem `YOUTUBE_REFRESH_TOKEN`, o passo de upload é pulado e o boletim continua
disponível como artefato do workflow.

## Limites

- **Cota:** a cota padrão é 10.000 unidades/dia e cada upload custa cerca de
  1.600, ou seja, cerca de 6 vídeos por dia. Com boletins a cada duas horas,
  os envios que passarem da cota terminam com aviso, sem falhar a geração.
  Para publicar os 12, solicitar aumento de cota ao Google.
- **App não verificado:** enquanto o projeto OAuth não passar pela auditoria
  do Google, os vídeos enviados pela API ficam privados, mesmo com
  `YOUTUBE_PRIVACY=public`.
- **Token de teste:** com a tela de consentimento em modo *Teste*, o refresh
  token expira em 7 dias. Publicar o app (*Em produção*) evita a expiração.
- Os vídeos são marcados como conteúdo sintético (apresentadora e voz por IA),
  categoria Notícias e idioma pt-BR. O resultado de cada envio fica em
  `youtube.json` na pasta do boletim.

## Render

Quando os boletins são gerados pelo serviço do Render (`VIDEO_AUTOSTART=true`),
cada job concluído é enviado ao YouTube pelo próprio worker. No painel do
Render, em *Environment*, preencher `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`
e `YOUTUBE_REFRESH_TOKEN` (declarados com `sync: false` no `render.yaml`).
O resultado aparece no campo `youtube` de `GET /v1/videos/{id}`; uma falha de
envio fica registrada ali sem marcar o vídeo como falho.

Se o Render só hospedar a API e a geração continuar no GitHub Actions,
configure os secrets no GitHub, não no Render, para não enviar o mesmo boletim
duas vezes.
