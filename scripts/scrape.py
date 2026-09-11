#!/usr/bin/env python3
"""
Buzón Ciudadano Vitoria-Gasteiz — scraper.
Descubre los sub-temas de cada área, recorre sus asuntos y genera docs/index.html.
Sin dependencias externas (solo librería estándar).
"""
import json, re, sys, time
from datetime import datetime, timedelta
from pathlib import Path
import urllib.request

BASE = "https://www.vitoria-gasteiz.org"

# Áreas de primer nivel del buzón
AREAS_RAIZ = {
    1:   "Movilidad y transporte",
    11:  "Espacio público",
    21:  "Medio ambiente y sostenibilidad",
    27:  "Información y atención ciudadana",
    34:  "Deportes",
    38:  "Ocio y cultura",
    43:  "Servicios sociales",
    47:  "Hacienda",
    58:  "Educación",
    63:  "Seguridad ciudadana",
    68:  "Salud y consumo",
    69:  "Urbanismo - Vivienda",
    76:  "Promoción económica",
    84:  "Formación y empleo",
    88:  "Convivencia y Cooperación",
    102: "Participación ciudadana",
    166: "Turismo",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9",
}
PAUSA = 0.4
AHORA = datetime.now()

# ── HTTP ───────────────────────────────────────────────────────────────────────

def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception:
            if i == 2:
                raise
            time.sleep(2)
    return ""

# ── Utilidades de parseo ───────────────────────────────────────────────────────

def limpiar(html):
    txt = re.sub(r"<[^>]+>", " ", html)
    txt = (txt.replace("&nbsp;", " ").replace("&amp;", "&")
              .replace("&quot;", '"').replace("&#39;", "'")
              .replace("&lt;", "<").replace("&gt;", ">")
              .replace("&aacute;", "á").replace("&eacute;", "é")
              .replace("&iacute;", "í").replace("&oacute;", "ó")
              .replace("&uacute;", "ú").replace("&ntilde;", "ñ"))
    return re.sub(r"\s+", " ", txt).strip()

MESES_REL = {
    "hora": "hours", "horas": "hours",
    "minuto": "minutes", "minutos": "minutes",
    "dia": "days", "dias": "days", "día": "days", "días": "days",
}

def parse_fecha(texto):
    """Convierte los formatos del buzón a datetime.
    Soporta: '09/09/2026 22:10:41', 'ayer 22:36', 'hoy 10:15',
             'hace 1 hora', 'hace 25 minutos'."""
    # Absoluta
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2}):(\d{2})", texto)
    if m:
        try:
            return datetime(int(m[3]), int(m[2]), int(m[1]),
                            int(m[4]), int(m[5]), int(m[6]))
        except ValueError:
            return None

    # "ayer HH:MM" / "hoy HH:MM"
    m = re.search(r"\b(ayer|hoy)\s+(\d{1,2}):(\d{2})", texto, re.I)
    if m:
        base = AHORA - timedelta(days=1) if m[1].lower() == "ayer" else AHORA
        return base.replace(hour=int(m[2]), minute=int(m[3]), second=0, microsecond=0)

    # "hace N unidad"
    m = re.search(r"hace\s+(\d+)\s+(minutos?|horas?|d[ií]as?)", texto, re.I)
    if m:
        n = int(m[1])
        unidad = MESES_REL.get(m[2].lower().rstrip("s") + ("s" if m[2].lower().endswith("s") else ""), None)
        u = m[2].lower()
        if u.startswith("minuto"):  return AHORA - timedelta(minutes=n)
        if u.startswith("hora"):    return AHORA - timedelta(hours=n)
        if u.startswith("d"):       return AHORA - timedelta(days=n)

    # "hace un/una unidad"
    m = re.search(r"hace\s+(un|una)\s+(minuto|hora|d[ií]a)", texto, re.I)
    if m:
        u = m[2].lower()
        if u.startswith("minuto"): return AHORA - timedelta(minutes=1)
        if u.startswith("hora"):   return AHORA - timedelta(hours=1)
        if u.startswith("d"):      return AHORA - timedelta(days=1)

    return None

ANIMOS = [
    ("Cara_emoticonoIracundo", "muy_triste"),
    ("Cara_emoticonoEnfadado", "triste"),
    ("Cara_emoticonoNormal",   "normal"),
    ("Cara_emoticonoAlegre",   "alegre"),
]

def parse_animo(bloque):
    for marca, valor in ANIMOS:
        if marca in bloque:
            return valor
    return "normal"

def parse_asuntos(html):
    """Extrae los asuntos de una página de listado."""
    enlaces = list(re.finditer(
        r'<a\s[^>]*href="([^"]*comentarioAction\.do[^"]*claveAsuntoCom=\d+[^"]*)"[^>]*>([\s\S]*?)</a>',
        html))
    asuntos = []
    for i, m in enumerate(enlaces):
        href   = m.group(1).replace("&amp;", "&")
        titulo = limpiar(m.group(2))
        if not titulo:
            continue
        ini = m.start()
        fin = enlaces[i + 1].start() if i + 1 < len(enlaces) else min(ini + 2500, len(html))
        bloque = html[ini:fin]

        fecha = parse_fecha(limpiar(bloque))
        if not fecha:
            continue

        animo = parse_animo(bloque)
        es_respuesta = "escudoayuntverde" in bloque

        # Extracto = texto del bloque sin el título ni la línea de metadatos
        txt = limpiar(bloque)
        if txt.startswith(titulo):
            txt = txt[len(titulo):].strip()
        txt = re.split(r"\s+\S*\s*(?:hace \d|hace un|ayer |hoy |\d{2}/\d{2}/\d{4})", txt)[0]
        extracto = txt.strip()[:260]

        asuntos.append({
            "titulo":   titulo,
            "url":      href if href.startswith("http") else BASE + href,
            "fecha":    fecha,
            "animo":    animo,
            "extracto": extracto,
            "respuesta_ayto": es_respuesta,
        })
    return asuntos

def tiene_siguiente(html):
    return bool(re.search(r'accionAsunto=navegarAsuntos[^"]*pagActual=\d+[^"]*"[^>]*>\s*Siguiente', html)) \
        or ">Siguiente<" in html

# ── Descubrimiento de sub-temas ────────────────────────────────────────────────

def sub_areas(html):
    """Devuelve [(clave, nombre)] de los sub-temas enlazados en la página."""
    out, vistos = [], set()
    for m in re.finditer(
        r'<a\s[^>]*href="[^"]*areaAction\.do[^"]*claveArea=(\d+)[^"]*"[^>]*>([\s\S]*?)</a>', html):
        clave = int(m.group(1))
        nombre = limpiar(m.group(2))
        if clave in vistos or not nombre:
            continue
        vistos.add(clave)
        out.append((clave, nombre))
    return out

def descubrir_hojas():
    """Recorre las áreas raíz y devuelve las hojas que contienen asuntos."""
    hojas = []       # [(clave, nombre_hoja, nombre_area_raiz)]
    for raiz, nombre_raiz in AREAS_RAIZ.items():
        url = f"{BASE}/wb021/was/areaAction.do?idioma=es&accion=areas&claveArea={raiz}"
        try:
            html = fetch(url)
        except Exception as e:
            print(f"  ⚠ área {raiz}: {e}", file=sys.stderr)
            continue

        if re.search(r'comentarioAction\.do[^"]*claveAsuntoCom=\d+', html):
            # La propia área raíz ya lista asuntos
            hojas.append((raiz, nombre_raiz, nombre_raiz))
        else:
            # Buscar sub-temas: enlaces a claveArea distintos de los del menú lateral
            menu = set(AREAS_RAIZ.keys())
            for clave, nombre in sub_areas(html):
                if clave not in menu:
                    hojas.append((clave, nombre, nombre_raiz))
        time.sleep(PAUSA)
    return hojas

# ── Scraping de una hoja ───────────────────────────────────────────────────────

def scrape_hoja(clave, desde, hasta):
    resultados = []
    for pag in range(1, 12):
        if pag == 1:
            url = f"{BASE}/wb021/was/areaAction.do?idioma=es&accion=areas&claveArea={clave}"
        else:
            url = (f"{BASE}/wb021/was/asuntoAction.do?idioma=es"
                   f"&accionAsunto=navegarAsuntos&pagActual={pag}"
                   f"&claveAreaAsunto={clave}&responsableAreaAsunto=")
        try:
            html = fetch(url)
        except Exception:
            break

        asuntos = parse_asuntos(html)
        if not asuntos:
            break

        parar = False
        for a in asuntos:
            if a["fecha"] < desde:
                parar = True
                break
            if a["fecha"] <= hasta:
                resultados.append(a)

        if parar or not tiene_siguiente(html):
            break
        time.sleep(PAUSA)
    return resultados

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    dias = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    hasta = AHORA
    desde = (AHORA - timedelta(days=dias)).replace(hour=0, minute=0, second=0, microsecond=0)

    print(f"Período: {desde:%d/%m/%Y} → {hasta:%d/%m/%Y}\n")
    print("Descubriendo temas del buzón…")
    hojas = descubrir_hojas()
    print(f"  {len(hojas)} temas encontrados\n")

    todos = []
    for clave, nombre, raiz in hojas:
        print(f"  {raiz} › {nombre}…", end=" ", flush=True)
        try:
            asuntos = scrape_hoja(clave, desde, hasta)
        except Exception as e:
            print(f"error: {e}")
            continue
        print(len(asuntos))
        for a in asuntos:
            todos.append({
                "titulo":   a["titulo"],
                "url":      a["url"],
                "fecha":    a["fecha"].isoformat(),
                "animo":    a["animo"],
                "extracto": a["extracto"],
                "respuesta_ayto": a["respuesta_ayto"],
                "tema":     nombre,
                "area":     raiz,
            })
        time.sleep(PAUSA)

    # Deduplicar por URL, ordenar cronológicamente
    unicos = {a["url"]: a for a in todos}
    todos = sorted(unicos.values(), key=lambda x: x["fecha"])

    print(f"\nTotal: {len(todos)} comentarios")

    Path("docs").mkdir(exist_ok=True)
    Path("docs/index.html").write_text(render(todos, desde, hasta), encoding="utf-8")
    print("docs/index.html generado ✓")

# ── Render HTML ────────────────────────────────────────────────────────────────

def render(datos, desde, hasta):
    import json
    rango    = f"{desde:%d/%m}–{hasta:%d/%m/%Y}"
    generado = AHORA.strftime("%d/%m/%Y %H:%M")
    payload  = json.dumps(datos, ensure_ascii=False)

    css = r"""
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
 --tinta:#16211c; --tinta-2:#233029; --papel:#eef0ea; --papel-2:#f7f8f4;
 --verde:#3aaf2d; --verde-h:#1b5e20; --gris:#6b7269; --linea:#d4d7cd;
 --m-alegre:#3aaf2d; --m-normal:#8a9088; --m-triste:#c8791f; --m-muy:#a32d1f;
 --d-alegre:#5fc84f; --d-normal:#7d857a; --d-triste:#e0a24a; --d-muy:#d4573f;
 --oro:#8a6d1f;
}
html{scroll-behavior:smooth}
body{font-family:'IBM Plex Sans',system-ui,sans-serif;font-size:15px;
 background:var(--papel);color:var(--tinta);line-height:1.55;
 -webkit-font-smoothing:antialiased}
.mono{font-family:'IBM Plex Mono',ui-monospace,monospace;font-variant-numeric:tabular-nums}

/* ── Cabecera ─────────────────────────────────────── */
.cab{background:var(--tinta);color:var(--papel-2);padding:1.4rem 1.6rem 1.1rem}
.cab-fila{display:flex;align-items:flex-end;gap:1rem;flex-wrap:wrap;
 max-width:1180px;margin:0 auto 1.1rem}
.cab h1{font-size:1.22rem;font-weight:600;letter-spacing:-.015em;line-height:1.2}
.cab h1 span{display:block;font-size:.76rem;font-weight:400;opacity:.55;
 letter-spacing:.02em;margin-top:.15rem}
.cab-num{margin-left:auto;text-align:right;line-height:1.15}
.cab-num b{font-size:1.55rem;font-weight:600;letter-spacing:-.02em}
.cab-num i{display:block;font-style:normal;font-size:.72rem;opacity:.55}

/* Franja de temperatura */
.strip{max-width:1180px;margin:0 auto;display:flex;gap:3px;align-items:flex-end}
.dcol{flex:1;display:flex;flex-direction:column;align-items:stretch;gap:.35rem;
 background:none;border:0;padding:0;cursor:pointer;font:inherit;color:inherit}
.dbar{display:flex;flex-direction:column-reverse;justify-content:flex-start;
 height:58px;border-radius:1px;overflow:hidden;background:rgba(255,255,255,.07)}
.dseg{width:100%}
.dseg.alegre{background:var(--d-alegre)} .dseg.normal{background:var(--d-normal)}
.dseg.triste{background:var(--d-triste)} .dseg.muy_triste{background:var(--d-muy)}
.dlab{font-size:.64rem;opacity:.5;text-align:center;letter-spacing:.03em}
.dcol:hover .dbar{outline:1px solid rgba(255,255,255,.35);outline-offset:1px}
.dcol:focus-visible{outline:2px solid var(--verde);outline-offset:3px}

/* ── Barra de herramientas ────────────────────────── */
.tools{position:sticky;top:0;z-index:20;background:var(--papel-2);
 border-bottom:1px solid var(--linea)}
.tools-in{max-width:1180px;margin:0 auto;padding:.6rem 1.6rem;
 display:flex;gap:.55rem;align-items:center;flex-wrap:wrap}
.tools input[type=search],.tools select{font:inherit;font-size:.85rem;
 border:1px solid var(--linea);background:#fff;color:var(--tinta);
 padding:.4rem .6rem;border-radius:2px;outline:none}
.tools input[type=search]{width:220px}
.tools input:focus,.tools select:focus{border-color:var(--verde);
 box-shadow:0 0 0 2px rgba(58,175,45,.16)}
.pill{font:inherit;font-size:.8rem;border:1px solid var(--linea);background:#fff;
 color:var(--gris);padding:.38rem .7rem;border-radius:2px;cursor:pointer}
.pill:hover{border-color:var(--verde);color:var(--verde-h)}
.pill[aria-pressed=true]{background:var(--oro);border-color:var(--oro);color:#fff}
.pill:disabled{opacity:.4;cursor:default}
.cnt{margin-left:auto;font-size:.78rem;color:var(--gris)}

/* ── Cuerpo ───────────────────────────────────────── */
.wrap{max-width:1180px;margin:0 auto;padding:1.4rem 1.6rem 4rem;
 display:grid;grid-template-columns:206px 1fr;gap:2.2rem;align-items:start}

.side{position:sticky;top:64px}
.side h2{font-size:.74rem;font-weight:600;color:var(--gris);
 padding-bottom:.45rem;border-bottom:1px solid var(--linea);margin-bottom:.3rem}
.tema{display:flex;width:100%;gap:.5rem;align-items:baseline;
 font:inherit;font-size:.82rem;text-align:left;background:none;border:0;
 padding:.3rem .35rem;cursor:pointer;color:var(--tinta);border-radius:2px;line-height:1.3}
.tema:hover{background:#e3e7dd}
.tema[aria-pressed=true]{background:var(--tinta);color:var(--papel-2)}
.tema em{font-style:normal;flex:1;min-width:0}
.tema b{font-weight:500;font-size:.74rem;opacity:.6}
.tema[aria-pressed=true] b{opacity:.8}

/* ── Lista ────────────────────────────────────────── */
.dia{display:flex;align-items:baseline;gap:.6rem;
 font-size:.76rem;font-weight:600;color:var(--verde-h);
 margin:1.9rem 0 .2rem;padding-bottom:.35rem;border-bottom:1px solid var(--linea);
 scroll-margin-top:66px}
.dia:first-child{margin-top:0}
.dia b{margin-left:auto;font-weight:400;font-size:.72rem;color:var(--gris)}

.it{display:grid;grid-template-columns:26px 46px 1fr;gap:0 .55rem;
 padding:.7rem 0 .7rem .1rem;border-bottom:1px solid var(--linea)}
.it:hover{background:#e8ebe3}
.star{background:none;border:0;cursor:pointer;padding:0;font-size:1.02rem;
 line-height:1.4;color:var(--linea);align-self:start;border-radius:2px}
.star:hover{color:var(--oro)}
.star[aria-pressed=true]{color:var(--oro)}
.hora{font-size:.76rem;color:var(--gris);align-self:start;padding-top:.12rem}
.cu{min-width:0;border-left:3px solid var(--m-normal);padding-left:.7rem}
.cu.alegre{border-color:var(--m-alegre)} .cu.triste{border-color:var(--m-triste)}
.cu.muy_triste{border-color:var(--m-muy)}
.ti{font-size:.95rem;font-weight:600;line-height:1.35}
.ti a{color:inherit;text-decoration:none}
.ti a:hover{color:var(--verde-h);text-decoration:underline;text-underline-offset:2px}
.mt{display:flex;gap:.5rem;align-items:baseline;flex-wrap:wrap;
 font-size:.74rem;color:var(--gris);margin-top:.12rem}
.resp{color:var(--oro);border:1px solid currentColor;padding:0 .3rem;
 border-radius:2px;font-size:.68rem}
.ex{font-size:.84rem;color:#4c544a;margin-top:.3rem;
 max-width:68ch;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
 overflow:hidden}

.vacio{padding:3.5rem 1rem;text-align:center;color:var(--gris);font-size:.9rem}
.vacio b{display:block;font-size:1rem;color:var(--tinta);
 font-weight:600;margin-bottom:.3rem}
.pie{border-top:1px solid var(--linea);margin-top:2.5rem;padding-top:1rem;
 font-size:.74rem;color:var(--gris)}

/* ── Responsive ───────────────────────────────────── */
@media(max-width:860px){
 .wrap{grid-template-columns:1fr;gap:1.2rem;padding:1rem 1rem 3rem}
 .side{position:static}
 .side-scroll{display:flex;gap:.4rem;overflow-x:auto;padding-bottom:.4rem;
  -webkit-overflow-scrolling:touch}
 .tema{width:auto;white-space:nowrap;border:1px solid var(--linea);flex:0 0 auto}
 .tools-in{padding:.55rem 1rem}
 .tools input[type=search]{width:100%;min-width:140px;flex:1}
 .cab{padding:1.1rem 1rem .9rem}
 .it{grid-template-columns:24px 42px 1fr}
 .dlab{font-size:.58rem}
}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*{transition:none!important}}
@media print{
 .tools,.side,.strip,.star{display:none!important}
 .wrap{display:block;max-width:none;padding:0}
 body{background:#fff;font-size:11pt}
 .cab{background:#fff;color:#000;border-bottom:2px solid #000;padding:0 0 .5rem}
 .it{break-inside:avoid;grid-template-columns:44px 1fr}
 .ex{-webkit-line-clamp:unset;overflow:visible}
 a{color:inherit;text-decoration:none}
}
"""

    js = r"""
const MOOD={alegre:'Alegre',normal:'Normal',triste:'Triste',muy_triste:'Muy triste'};
const ORDEN=['muy_triste','triste','normal','alegre'];
let marcados=new Set();
try{marcados=new Set(JSON.parse(localStorage.getItem('buzon_marcados')||'[]'))}catch(e){}
function guardar(){try{localStorage.setItem('buzon_marcados',
  JSON.stringify([...marcados]))}catch(e){}}

let soloMarcados=false, temaSel='';

const $=id=>document.getElementById(id);
const diaKey=d=>d.slice(0,10);
const fmtDia=iso=>new Date(iso).toLocaleDateString('es-ES',
  {weekday:'long',day:'numeric',month:'long'});

/* ── Franja de temperatura ── */
function pintarStrip(){
  const dias={};
  for(const d of D){const k=diaKey(d.fecha);
    (dias[k]=dias[k]||{total:0,alegre:0,normal:0,triste:0,muy_triste:0});
    dias[k].total++; dias[k][d.animo]++;}
  const claves=Object.keys(dias).sort();
  const max=Math.max(1,...claves.map(k=>dias[k].total));
  $('strip').innerHTML=claves.map(k=>{
    const v=dias[k], alto=Math.round(v.total/max*100);
    const segs=ORDEN.filter(m=>v[m]).map(m=>
      `<div class="dseg ${m}" style="height:${v[m]/v.total*100}%"></div>`).join('');
    const dt=new Date(k+'T12:00:00');
    const lab=dt.toLocaleDateString('es-ES',{weekday:'short'}).slice(0,3)
      +' '+dt.getDate();
    return `<button class="dcol" data-dia="${k}"
      title="${v.total} comentarios">
      <div class="dbar"><div style="height:${alto}%;display:flex;
        flex-direction:column-reverse;margin-top:auto">${segs}</div></div>
      <span class="dlab">${lab}</span></button>`;
  }).join('');
  $('strip').querySelectorAll('.dcol').forEach(b=>b.onclick=()=>{
    const el=document.getElementById('d-'+b.dataset.dia);
    if(el)el.scrollIntoView({block:'start'});});
}

/* ── Barra lateral de temas ── */
function pintarTemas(){
  const c={};
  for(const d of D) c[d.tema]=(c[d.tema]||0)+1;
  const lista=Object.entries(c).sort((a,b)=>b[1]-a[1]);
  $('temas').innerHTML=
    `<button class="tema" data-t="" aria-pressed="${temaSel===''}">
       <em>Todos los temas</em><b class="mono">${D.length}</b></button>`
    +lista.map(([t,n])=>`<button class="tema" data-t="${t.replace(/"/g,'&quot;')}"
       aria-pressed="${temaSel===t}"><em>${t}</em><b class="mono">${n}</b></button>`).join('');
  $('temas').querySelectorAll('.tema').forEach(b=>b.onclick=()=>{
    temaSel = (temaSel===b.dataset.t) ? '' : b.dataset.t;
    pintarTemas(); render();});
}

/* ── Filtrado y lista ── */
function filtrados(){
  const q=$('q').value.toLowerCase().trim(), m=$('m').value;
  return D.filter(d=>{
    if(soloMarcados && !marcados.has(d.url)) return false;
    if(temaSel && d.tema!==temaSel) return false;
    if(m && d.animo!==m) return false;
    if(q && !(d.titulo+' '+(d.extracto||'')+' '+d.tema).toLowerCase().includes(q))
      return false;
    return true;});
}

function render(){
  const v=filtrados();
  $('cnt').textContent = v.length===D.length
    ? `${D.length} comentarios`
    : `${v.length} de ${D.length}`;
  $('nmarc').textContent = marcados.size;
  $('btnMarc').disabled = marcados.size===0;
  $('btnCopiar').disabled = marcados.size===0;

  if(!v.length){
    $('lista').innerHTML=`<p class="vacio"><b>Nada que mostrar</b>
      Prueba a quitar algún filtro o a buscar otra palabra.</p>`;
    return;}

  let h='',prev='';
  for(const d of v){
    const k=diaKey(d.fecha);
    if(k!==prev){
      const n=v.filter(x=>diaKey(x.fecha)===k).length;
      h+=`<h3 class="dia" id="d-${k}">${fmtDia(d.fecha)}
          <b class="mono">${n}</b></h3>`;
      prev=k;}
    const hora=new Date(d.fecha).toLocaleTimeString('es-ES',
      {hour:'2-digit',minute:'2-digit'});
    const on=marcados.has(d.url);
    h+=`<article class="it">
      <button class="star" aria-pressed="${on}" data-u="${d.url}"
        title="${on?'Quitar de la selección':'Marcar para el programa'}"
        aria-label="${on?'Quitar de la selección':'Marcar para el programa'}"
        >${on?'★':'☆'}</button>
      <span class="hora mono">${hora}</span>
      <div class="cu ${d.animo}">
        <h4 class="ti"><a href="${d.url}" target="_blank" rel="noopener">${d.titulo}</a></h4>
        <p class="mt"><span>${d.tema}</span><span>${MOOD[d.animo]||d.animo}</span>
          ${d.respuesta_ayto?'<span class="resp">respondido</span>':''}</p>
        ${d.extracto?`<p class="ex">${d.extracto}</p>`:''}
      </div></article>`;}
  $('lista').innerHTML=h;
  $('lista').querySelectorAll('.star').forEach(b=>b.onclick=()=>{
    const u=b.dataset.u;
    marcados.has(u)?marcados.delete(u):marcados.add(u);
    guardar(); render();});
}

/* ── Acciones ── */
$('q').oninput=render;
$('m').onchange=render;
$('btnMarc').onclick=()=>{
  soloMarcados=!soloMarcados;
  $('btnMarc').setAttribute('aria-pressed',soloMarcados);
  $('btnMarc').textContent=soloMarcados?'Ver todos':'Ver solo marcados';
  render();};
$('btnCopiar').onclick=async()=>{
  const sel=D.filter(d=>marcados.has(d.url))
    .sort((a,b)=>a.fecha.localeCompare(b.fecha));
  const txt=sel.map(d=>{
    const f=new Date(d.fecha).toLocaleDateString('es-ES',
      {day:'2-digit',month:'2-digit'})+' '+
      new Date(d.fecha).toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'});
    return `${f} · ${d.tema}\n${d.titulo}\n${d.extracto||''}\n${d.url}\n`;
  }).join('\n');
  try{await navigator.clipboard.writeText(txt);
    $('btnCopiar').textContent='Copiado';
    setTimeout(()=>$('btnCopiar').textContent='Copiar selección',1600);
  }catch(e){
    $('btnCopiar').textContent='No se pudo copiar';
    setTimeout(()=>$('btnCopiar').textContent='Copiar selección',1600);}};

pintarStrip(); pintarTemas(); render();
"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Buzón Ciudadano · {rango}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>{css}</style>
</head>
<body>

<header class="cab">
  <div class="cab-fila">
    <h1>Buzón Ciudadano<span>Vitoria-Gasteiz · {rango}</span></h1>
    <div class="cab-num">
      <b class="mono">{len(datos)}</b>
      <i>comentarios esta semana</i>
    </div>
  </div>
  <div class="strip" id="strip"></div>
</header>

<div class="tools">
  <div class="tools-in">
    <input type="search" id="q" placeholder="Buscar una calle, un barrio, un tema…"
           aria-label="Buscar">
    <select id="m" aria-label="Filtrar por estado de ánimo">
      <option value="">Cualquier ánimo</option>
      <option value="muy_triste">Muy triste</option>
      <option value="triste">Triste</option>
      <option value="normal">Normal</option>
      <option value="alegre">Alegre</option>
    </select>
    <button class="pill" id="btnMarc" aria-pressed="false">Ver solo marcados</button>
    <button class="pill" id="btnCopiar">Copiar selección</button>
    <span class="cnt"><span id="cnt"></span> · <span id="nmarc" class="mono">0</span> marcados</span>
  </div>
</div>

<main class="wrap">
  <nav class="side">
    <h2>Temas de la semana</h2>
    <div id="temas" class="side-scroll"></div>
  </nav>
  <div>
    <div id="lista"></div>
    <footer class="pie">
      Actualizado el {generado}. Los datos proceden del Buzón Ciudadano
      del Ayuntamiento de Vitoria-Gasteiz; cada título enlaza al comentario original.
    </footer>
  </div>
</main>

<script>
const D={payload};
{js}
</script>
</body>
</html>"""


if __name__ == "__main__":
    main()
