"""Capture explicit products from the real app, preserving evidence per scene."""
from pathlib import Path
import os
from .segments import Segment

CLEAN_CSS = '''
.topbar, .map-rail, .chat, .map-hint, .toast { display:none!important; }
.stage { --chat-h:0px!important; background:#091422!important; }
.leaflet-container { background:#091422!important; }
/* Recolor only base tiles: meteorological pixels retain their original values. */
.base-tiles img { filter:invert(1) hue-rotate(180deg) saturate(.24) brightness(.68) contrast(1.12)!important; }
/* Forecasts retain the original light base so city labels stay readable. */
.trovox-forecast .base-tiles img {filter:saturate(.55) brightness(1.03)!important;}
.trovox-forecast .leaflet-container {background:#e8edf1!important;}
.legend { font-size:20px!important; width:320px!important; max-width:320px!important;
 bottom:38px!important; left:auto!important; right:18px!important; padding:16px 18px!important;
 background:rgba(9,20,34,.97)!important; color:#f1f7ff!important;
 border:1px solid #4bd7e5!important; border-radius:12px!important;
 box-shadow:0 8px 28px #0008!important; line-height:1.35!important; }
.legend-title { font-size:23px!important; color:#f1f7ff!important; font-weight:700!important; }
.legend-note,.legend-msg,.legend-scale,.legend-valid {font-size:18px!important;color:#e0eafa!important;}
.legend strong,.legend b {color:#fff!important;}
.leaflet-bottom {bottom:0!important;}
.cloud-player,.anim-ends,.legend-toggle,.step-picker,.legend-why {display:none!important;}
.leaflet-control-attribution {font-size:12px!important;background:#091422e8!important;color:#d8e7fa!important;}
.leaflet-control-attribution a {color:#8ae6ee!important;}
.country-label span {font-size:17px!important;font-weight:700!important;color:#fff!important;
 text-shadow:-1px -1px 2px #091422,1px 1px 2px #091422,0 0 5px #091422!important;}
.leaflet-tooltip {font-size:23px!important;font-weight:700!important;color:#fff!important;
 background:#102337f5!important;border:2px solid #65e0d0!important;
 border-radius:7px!important;padding:8px 12px!important;box-shadow:0 3px 14px #0009!important;}
.leaflet-tooltip-right:before {border-right-color:#65e0d0!important;}
'''


def capture_segments(app_url: str, segments: list[Segment], directory: Path):
    from playwright.sync_api import sync_playwright
    directory.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,
            executable_path=os.environ.get('CHROMIUM_BIN') or '/opt/google/chrome/chrome',
            args=['--no-sandbox','--disable-gpu'])
        page = browser.new_page(viewport={'width':1440,'height':810}, timezone_id='America/Belem', color_scheme='light')
        page.goto(app_url, wait_until='domcontentloaded', timeout=90000)
        page.wait_for_function('typeof mapInfo !== "undefined" && mapInfo && typeof nowcastInfo !== "undefined" && nowcastInfo', timeout=90000)
        page.evaluate('setPlaying(false);setNowcastPlaying(false);setObservedOn(false);setCloudsOn(false);setRadarOn(false)')
        # Capture at the actual output-panel size: no tiny downscaled controls.
        for s in segments:
            if s.view == 'summary':
                continue
            try:
                forecast_scene = s.category in ('previsao', 'destaque')
                page.emulate_media(color_scheme='light')
                page.evaluate('(enabled)=>document.documentElement.classList.add("trovox-forecast")', forecast_scene)
                page.evaluate("""() => {
                    document.querySelector('#map-rail').dataset.open='true';
                    clearRegion();map.closePopup();map.options.zoomSnap=0.1;
                    if(marker){map.removeLayer(marker);marker=null;}
                    map.fitBounds([[-57,-82],[13,-34]],{animate:false,padding:[50,50]});
                }""")
                if s.place:
                    # These coordinates come from the agent's structured place response.
                    page.evaluate('''(p)=>{
                        map.fitBounds([[Math.max(-85,p.lat-2),p.lon-3],[Math.min(85,p.lat+2),p.lon+3]],
                            {animate:false,paddingTopLeft:[55,105],paddingBottomRight:[370,65],maxZoom:7});
                        const label=document.createElement('span');label.textContent=p.nome;
                        marker=L.circleMarker([p.lat,p.lon],{radius:10,color:'#65e0d0',weight:3,
                            fillColor:'#102337',fillOpacity:1}).addTo(map)
                            .bindTooltip(label,{permanent:true,direction:'right'}).openTooltip();
                    }''',s.place)
                elif s.category in ('nowcasting','observacao','alagamento','extrapolacao'):
                    page.evaluate('void map.fitBounds([[-35,-74],[6,-34]],{animate:false,padding:[40,40]})')
                group = 'previsao' if s.category in ('previsao','destaque') else 'nowcasting'
                page.evaluate('(v)=>{const g=grupoDaVista(v);if(g)abreGrupo(g)}',s.view)
                # Choose ECENS before selecting its product. The rain button can
                # be disabled while the UI is still showing the GFS product list.
                if s.category in ('previsao','destaque'):
                    source_button = page.locator(f'[data-fonte="{s.source}"]')
                    if page.evaluate('fonte') != s.source:
                        source_button.click(timeout=15000)
                    page.wait_for_function('(v)=>fonte===v',arg=s.source,timeout=15000)
                if page.evaluate('currentView') != s.view:
                    page.locator(f'[data-view="{s.view}"]').click(timeout=15000)
                else:
                    page.evaluate('async()=>{forecastOn=true; await setProduct(VISTAS[currentView].produto,true);showForecast();renderLegend()}')
                if s.category in ('previsao','destaque'):
                    page.wait_for_function('(v)=>fonte===v && forecastOn',arg=s.source,timeout=15000)
                page.evaluate('setPlaying(false);setNowcastPlaying(false);setObservedOn(false);setCloudsOn(false);setRadarOn(false)')
                if s.view in ('agora','extrapolacao'):
                    horizon = s.horizon or 0
                    page.evaluate('(h)=>{forecastOn=true;setNowcastFrame(h);setNowcastPlaying(false)}',horizon)
                    page.wait_for_function('''(h)=>nowcastOverlays.some(o=>map.hasLayer(o)&&o.options.opacity>0&&o.getElement()?.complete&&o.getElement()?.naturalWidth>0&&o.getElement().src.includes('minutos='+h))''',arg=horizon,timeout=60000)
                elif s.view in ('severidade','inundacoes'):
                    page.wait_for_function('rainAreaFeita !== null && severeLayer !== null',timeout=90000)
                else:
                    expected = '/previsao/chuva/' if s.view=='chuva-prevista' else f'/previsao/mapa/{s.view}.png'
                    page.wait_for_function('''(args)=>overlay && map.hasLayer(overlay) && overlay.getElement()?.complete && overlay.getElement()?.naturalWidth>0 && overlay.getElement().src.includes(args.path) && overlay.getElement().src.includes('fonte='+args.source)''',arg={'path':expected,'source':s.source},timeout=90000)
                if s.category == 'observacao':
                    page.evaluate('setObservedOn(true);showFrame(FRAME_COUNT-1,true)')
                page.wait_for_function('''()=>[...document.querySelectorAll('.leaflet-tile')].every(i=>i.complete)&&!document.querySelector('.leaflet-zoom-anim')''',timeout=30000)
                s.metadata = page.evaluate('''()=>({view:currentView,source:fonte,product,period:document.querySelector('#period').textContent,
                    map:mapInfo,rain:rainInfo,nowcast:nowcastInfo,legend:document.querySelector('#legend').innerText,
                    polygon_count:severeLayer?.getLayers().filter(x=>x.options.fill!==false&&map.getBounds().intersects(x.getBounds())).length||0,
                    polygon_evidence:severeLayer?.getLayers().filter(x=>x.options.fill!==false&&map.getBounds().intersects(x.getBounds())).map(x=>({
                        color:x.options.fillColor||x.options.color,
                        bounds:[[x.getBounds().getSouth(),x.getBounds().getWest()],[x.getBounds().getNorth(),x.getBounds().getEast()]],
                        created_at:x.options.nascidoEm||null
                    }))||[],
                    analysis_bounds:rainAreaFeita?[[rainAreaFeita.getSouth(),rainAreaFeita.getWest()],[rainAreaFeita.getNorth(),rainAreaFeita.getEast()]]:null,
                    bounds:[[map.getBounds().getSouth(),map.getBounds().getWest()],[map.getBounds().getNorth(),map.getBounds().getEast()]],
                    loaded_overlays:[...document.querySelectorAll('.leaflet-image-layer')].filter(x=>x.complete&&x.naturalWidth).map(x=>x.src)})''')
                if s.category not in ('previsao','destaque'):
                    s.metadata['model_selector_state'] = s.metadata['source']
                    s.metadata['source'] = 'monitoramento'
                if s.horizon and s.horizon not in (s.metadata.get('nowcast') or {}).get('horizontes_min',[]):
                    raise RuntimeError('horizonte indisponível')
                if s.category in ('previsao','destaque'):
                    # The app's generic attribution lists GFS even when ECENS is
                    # selected. Correct only that source label for this capture.
                    page.evaluate(r"""()=>{
                        const el=document.querySelector('.leaflet-control-attribution');
                        if(el)el.innerHTML=el.innerHTML.replace(/\bGFS\b/g,'ECENS');
                    }""")
                    s.metadata['attribution'] = page.locator('.leaflet-control-attribution').inner_text()
                    if 'GFS' in s.metadata['attribution']:
                        raise RuntimeError('rodapé genérico GFS não foi corrigido na captura ECENS')
                style = page.add_style_tag(content=CLEAN_CSS)
                page.evaluate("""()=>{map.invalidateSize({animate:false});renderLegend();
                }""")
                # Normalize only visible legend copy, never source data or layer URLs.
                page.evaluate(r'''()=>{
                    const root=document.querySelector('.legend');if(!root)return;
                    const formatter=new Intl.DateTimeFormat('pt-BR',{timeZone:'UTC',
                        day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
                    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
                    let node;while(node=walker.nextNode()){
                        node.nodeValue=node.nodeValue.replace(/\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})\b/g,
                            value=>{const d=new Date(value);return Number.isNaN(d.getTime())?value:formatter.format(d)+' UTC';})
                            .replace(/\b(\d{1,2}:\d{2}(?::\d{2})?)\s*Z\b/g,'$1 UTC')
                            .replace(/\bUTC(?:\s+UTC)+\b/g,'UTC');
                    }
                }''')
                # Hide menus by their actual UI state as well as the capture CSS.
                page.evaluate("document.querySelector('#map-rail').dataset.open='false'")
                page.wait_for_timeout(500)
                image = directory/f'{s.id}.png'
                page.locator('.stage').screenshot(path=str(image))
                style.evaluate('(e)=>e.remove()')
                s.metadata['presentation_style'] = 'trovox-light-v2'
                s.image = str(image.resolve())
            except Exception as exc:
                s.available = False
                s.metadata = {'error':str(exc)[:700]}
                # Recover the capture-only stylesheet on a failed scene.
                page.evaluate("document.querySelectorAll('style').forEach(s=>{if(s.textContent.includes('.legend-toggle'))s.remove()})")
        browser.close()
    return segments
