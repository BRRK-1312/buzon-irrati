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
    rango    = f"{desde:%d/%m/%Y} – {hasta:%d/%m/%Y}"
    generado = AHORA.strftime("%d/%m/%Y %H:%M")
    areas    = sorted({d["area"] for d in datos})
    opts     = "\n".join(f'<option value="{a}">{a}</option>' for a in areas)
    payload  = json.dumps(datos, ensure_ascii=False)

    css = """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--azul:#1a2535;--verde:#1d6a3e;--verde-l:#e6f2ec;--fondo:#f8f7f4;
--borde:#dddbd6;--texto:#1c1c1a;--meta:#6b6860;--blanco:#fff;--ayto:#8a6d1f}
body{font-family:system-ui,-apple-system,sans-serif;font-size:14px;
background:var(--fondo);color:var(--texto);line-height:1.5}
.cab{background:var(--azul);color:var(--blanco);padding:1rem 1.5rem;
display:flex;align-items:baseline;gap:1rem;flex-wrap:wrap}
.cab b{font-size:1rem;font-weight:600}
.cab .r{font-size:.78rem;opacity:.55}
.cab .n{margin-left:auto;font-size:.78rem;background:var(--verde);padding:.2rem .6rem}
.filtros{position:sticky;top:0;z-index:10;background:var(--blanco);
border-bottom:1px solid var(--borde);padding:.65rem 1.5rem;display:flex;
gap:.7rem;flex-wrap:wrap;align-items:center}
.filtros input,.filtros select{font:inherit;font-size:.82rem;border:1px solid var(--borde);
background:var(--fondo);padding:.35rem .6rem;outline:none;border-radius:0}
.filtros input{width:200px}
.filtros input:focus,.filtros select:focus{border-color:var(--verde)}
.cnt{margin-left:auto;font-size:.78rem;color:var(--meta)}
.lista{max-width:840px;margin:0 auto;padding:1.2rem 1.5rem 3rem}
.dia{font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;color:var(--verde);
margin:1.6rem 0 .5rem;padding-bottom:.3rem;border-bottom:1px solid var(--borde)}
.dia:first-child{margin-top:0}
.it{padding:.85rem 0;border-bottom:1px solid var(--borde);display:grid;
grid-template-columns:52px 1fr;gap:0 1rem}
.hora{font-size:.72rem;color:var(--meta);padding-top:.15rem}
.cu{min-width:0}
.mt{display:flex;gap:.45rem;align-items:center;flex-wrap:wrap;margin-bottom:.15rem}
.tag{font-size:.67rem;background:var(--verde-l);color:var(--verde);padding:.1rem .4rem}
.ani{font-size:.67rem;color:var(--meta)}
.resp{font-size:.67rem;color:var(--ayto);border:1px solid currentColor;padding:0 .3rem}
.ti{font-size:.92rem;font-weight:600;line-height:1.35;margin-bottom:.15rem}
.ti a{color:inherit;text-decoration:none}
.ti a:hover{color:var(--verde)}
.ex{font-size:.81rem;color:var(--meta)}
.vacio{text-align:center;padding:3rem 1rem;color:var(--meta)}
.pie{max-width:840px;margin:0 auto;padding:1rem 1.5rem 2rem;font-size:.72rem;color:var(--meta)}
@media(max-width:560px){.it{grid-template-columns:1fr;gap:.1rem}
.filtros{padding:.5rem 1rem}.lista{padding:1rem 1rem 3rem}}
@media print{.filtros{display:none}.it{break-inside:avoid}a{color:inherit;text-decoration:none}}
"""

    js = """
const A={muy_triste:'😠 Muy triste',triste:'😟 Triste',normal:'😐 Normal',alegre:'😊 Alegre'};
function f(){
 const q=document.getElementById('q').value.toLowerCase().trim();
 const a=document.getElementById('a').value;
 const m=document.getElementById('m').value;
 const v=D.filter(d=>{
  if(q&&!d.titulo.toLowerCase().includes(q)&&!(d.extracto||'').toLowerCase().includes(q)
     &&!d.tema.toLowerCase().includes(q))return false;
  if(a&&d.area!==a)return false;
  if(m&&d.animo!==m)return false;
  return true;});
 document.getElementById('cnt').textContent=v.length+' de '+D.length;
 document.getElementById('n').textContent=v.length+' comentarios';
 const L=document.getElementById('lista');
 if(!v.length){L.innerHTML='<p class="vacio">Sin resultados.</p>';return;}
 let html='',diaPrev='';
 for(const d of v){
  const dt=new Date(d.fecha);
  const dia=dt.toLocaleDateString('es-ES',{weekday:'long',day:'numeric',month:'long'});
  if(dia!==diaPrev){html+='<div class="dia">'+dia+'</div>';diaPrev=dia;}
  const hora=dt.toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'});
  html+='<div class="it"><div class="hora">'+hora+'</div><div class="cu">'
   +'<div class="mt"><span class="tag">'+d.tema+'</span>'
   +'<span class="ani">'+(A[d.animo]||d.animo)+'</span>'
   +(d.respuesta_ayto?'<span class="resp">respondido</span>':'')+'</div>'
   +'<div class="ti"><a href="'+d.url+'" target="_blank">'+d.titulo+'</a></div>'
   +(d.extracto?'<div class="ex">'+d.extracto+'</div>':'')
   +'</div></div>';
 }
 L.innerHTML=html;
}
f();
"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Buzón Ciudadano · {rango}</title>
<style>{css}</style>
</head>
<body>
<header class="cab">
  <b>Buzón Ciudadano · Vitoria-Gasteiz</b>
  <span class="r">{rango}</span>
  <span class="n" id="n">{len(datos)} comentarios</span>
</header>
<div class="filtros">
  <input type="search" id="q" placeholder="Buscar…" oninput="f()">
  <select id="a" onchange="f()"><option value="">Todas las áreas</option>
{opts}
  </select>
  <select id="m" onchange="f()"><option value="">Todos los estados</option>
    <option value="alegre">😊 Alegre</option>
    <option value="normal">😐 Normal</option>
    <option value="triste">😟 Triste</option>
    <option value="muy_triste">😠 Muy triste</option>
  </select>
  <span class="cnt" id="cnt"></span>
</div>
<div class="lista" id="lista"></div>
<footer class="pie">Actualizado: {generado} · Fuente: Buzón Ciudadano del Ayuntamiento de Vitoria-Gasteiz</footer>
<script>
const D={payload};
{js}
</script>
</body>
</html>"""

if __name__ == "__main__":
    main()
