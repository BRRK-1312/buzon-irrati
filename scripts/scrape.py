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
import http.cookiejar

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
PAUSA = 0.2
TRASLADO = "Para un funcionamiento más eficaz del buzón ciudadano"
AHORA = datetime.now()

# ── HTTP ───────────────────────────────────────────────────────────────────────

# La paginación del buzón depende de la sesión (cookie): la página 2+ devuelve
# el área visitada por última vez en esa sesión. Sin cookie, llega vacía.
_opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    for i in range(3):
        try:
            with _opener.open(req, timeout=25) as r:
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

        # Pie del listado: muestra el ÚLTIMO mensaje del hilo. Si lo escribió
        # el Ayuntamiento, no aparece ningún autor (primer <span> = fecha).
        pie = bloque[bloque.find("comment-icons"):] if "comment-icons" in bloque else ""
        spans = [limpiar(s) for s in re.findall(r"<span>([\s\S]*?)</span>", pie)]
        autor = spans[0] if spans and not parse_fecha(spans[0]) else ""
        n_com  = re.search(r'comentarios\.png"[^>]*>\s*:\s*(\d+)', bloque)
        n_part = re.search(r'participantes\.png"[^>]*>\s*:\s*(\d+)', bloque)
        canal = ("movil" if "telefonomovil.png" in bloque
                 else "web" if "paginaweb.png" in bloque else "")

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
            "autor":    autor,
            "ultimo_ayto": not autor,
            "n_comentarios":  int(n_com[1]) if n_com else 1,
            "n_participantes": int(n_part[1]) if n_part else 1,
            "canal":    canal,
        })
    return asuntos

def parse_hilo(html):
    """Mensajes de la página de un hilo: [(autor, fecha, es_ayto)]."""
    out = []
    for m in re.finditer(r'<li(?:\s+class="([^"]*)")?\s+id="CM\d+">([\s\S]*?)</li>', html):
        pie = re.search(r'<p class="pie">([\s\S]*?)</p>', m[2])
        if not pie:
            continue
        txt = limpiar(pie[1])
        fecha = parse_fecha(txt)
        if not fecha:
            continue
        corte = re.search(r"\d{2}/\d{2}/\d{4}|\b(?:ayer|hoy)\s+\d|hace\s", txt, re.I)
        autor = txt[:corte.start()].strip() if corte else txt
        es_ayto = "respuesta" in (m[1] or "") or autor == "El Ayuntamiento"
        out.append((autor, fecha, es_ayto))
    return out

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
        # Hilos trasladados a otro tema: el original queda con un aviso municipal
        # y el hilo reaparece en su tema nuevo. Se descarta el original.
        asuntos = [a for a in asuntos if not a["extracto"].startswith(TRASLADO)]
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
                "autor":    a["autor"],
                "ultimo_ayto": a["ultimo_ayto"],
                "n_comentarios":  a["n_comentarios"],
                "n_participantes": a["n_participantes"],
                "canal":    a["canal"],
                # Reactivado: ya hubo respuesta municipal y el último en escribir es un vecino
                "reactivado": a["respuesta_ayto"] and not a["ultimo_ayto"] and a["n_comentarios"] > 1,
            })
        time.sleep(PAUSA)

    # Deduplicar por URL, ordenar cronológicamente
    unicos = {a["url"]: a for a in todos}
    todos = sorted(unicos.values(), key=lambda x: x["fecha"])

    print(f"\nTotal: {len(todos)} comentarios")

    # Mensajes de vecinos dentro del período (el listado solo enseña el último)
    hilos = [a for a in todos if a["n_comentarios"] > 1]
    print(f"Leyendo {len(hilos)} hilos con varios mensajes…")
    for a in todos:
        a["vecinos"] = ([{"autor": a["autor"], "fecha": a["fecha"]}]
                        if a["n_comentarios"] <= 1 and a["autor"] else [])
    for a in hilos:
        try:
            mensajes = parse_hilo(fetch(a["url"]))
        except Exception as e:
            print(f"  ⚠ {a['url']}: {e}", file=sys.stderr)
            mensajes = []
        a["vecinos"] = [{"autor": au, "fecha": f.isoformat()}
                        for au, f, es_ayto in mensajes
                        if not es_ayto and desde <= f <= hasta]
        if not mensajes and a["autor"]:          # fallback: lo que dice el listado
            a["vecinos"] = [{"autor": a["autor"], "fecha": a["fecha"]}]
        time.sleep(PAUSA)

    hist = guardar_historico(todos, desde)
    resumen = analizar(todos, hist, desde, dias)

    Path("docs").mkdir(exist_ok=True)
    Path("docs/index.html").write_text(render(todos, desde, hasta, resumen), encoding="utf-8")
    print("docs/index.html generado ✓")

# ── Histórico y comparativas ───────────────────────────────────────────────────

DATA = Path("data")

def guardar_historico(todos, desde):
    """Guarda los asuntos en data/AAAA-Www.json (semana ISO de su fecha),
    fusionando con lo ya guardado. Devuelve todo el histórico en una lista."""
    DATA.mkdir(exist_ok=True)
    por_semana = {}
    for a in todos:
        y, w, _ = datetime.fromisoformat(a["fecha"]).isocalendar()
        por_semana.setdefault(f"{y}-W{w:02d}", []).append(a)
    for sem, nuevos in por_semana.items():
        f = DATA / f"{sem}.json"
        viejos = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
        mezcla = {(a["url"], a["fecha"]): a for a in viejos + nuevos}
        f.write_text(json.dumps(sorted(mezcla.values(), key=lambda x: x["fecha"]),
                                ensure_ascii=False, indent=0), encoding="utf-8")

    # Desde cuándo hay datos completos (el período más antiguo que se ha pedido)
    cob = DATA / "_cobertura.json"
    previo = json.loads(cob.read_text())["desde"] if cob.exists() else desde.isoformat()
    cob.write_text(json.dumps({"desde": min(previo, desde.isoformat())}))

    hist = []
    for f in sorted(DATA.glob("????-W??.json")):
        hist += json.loads(f.read_text(encoding="utf-8"))
    return hist

def analizar(todos, hist, desde, dias):
    """Comparativa por tema, autores frecuentes y hilos reactivados."""
    cobertura = datetime.fromisoformat(json.loads((DATA / "_cobertura.json").read_text())["desde"])
    paso = timedelta(days=dias)

    def ventana(k):
        """Asuntos con actividad en el período k (1 = el anterior al actual)."""
        ini, fin = desde - k * paso, desde - (k - 1) * paso
        if ini < cobertura:
            return None
        return {a["url"]: a for a in hist
                if ini <= datetime.fromisoformat(a["fecha"]) < fin}.values()

    def por_tema(asuntos):
        c = {}
        for a in asuntos:
            c[a["tema"]] = c.get(a["tema"], 0) + 1
        return c

    ahora = por_tema(todos)
    previas = [v for v in (ventana(k) for k in range(1, 5)) if v is not None]
    ant = por_tema(previas[0]) if previas else None
    temas = []
    for t in set(ahora) | set(ant or {}):
        media = (sum(por_tema(v).get(t, 0) for v in previas) / len(previas)) if previas else None
        temas.append({"tema": t, "ahora": ahora.get(t, 0),
                      "antes": (ant or {}).get(t, 0) if ant is not None else None,
                      "media": round(media, 1) if media is not None else None})

    # Autores: mensajes de vecinos en el período (y en los anteriores disponibles)
    def autores(asuntos):
        c = {}
        for a in asuntos:
            for v in a.get("vecinos", []):
                d = c.setdefault(v["autor"], {"mensajes": 0, "asuntos": set()})
                d["mensajes"] += 1
                d["asuntos"].add(a["titulo"])
        return c
    act = autores(todos)
    prev = [autores(v) for v in previas]
    lista = []
    for au, d in act.items():
        lista.append({"autor": au, "mensajes": d["mensajes"],
                      "asuntos": len(d["asuntos"]),
                      "semanas_previas": sum(1 for p in prev if au in p)})
    lista.sort(key=lambda x: (-x["mensajes"], x["autor"]))
    total_msj = sum(x["mensajes"] for x in lista)

    return {"temas": temas, "n_previas": len(previas),
            "autores": lista, "total_mensajes": total_msj}

# ── Render HTML ────────────────────────────────────────────────────────────────

def render(datos, desde, hasta, resumen):
    import json
    rango    = f"{desde:%d/%m}–{hasta:%d/%m/%Y}"
    generado = AHORA.strftime("%d/%m/%Y %H:%M")
    payload  = json.dumps(datos, ensure_ascii=False)
    payload_r = json.dumps(resumen, ensure_ascii=False)

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

/* ── Resumen semanal ──────────────────────────────── */
.res{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1.4rem;
 margin-bottom:2rem;padding-bottom:1.4rem;border-bottom:2px solid var(--tinta)}
.res h2{font-size:.74rem;font-weight:600;color:var(--gris);
 padding-bottom:.45rem;border-bottom:1px solid var(--linea);margin-bottom:.35rem;
 display:flex;gap:.5rem;align-items:baseline}
.res h2 b{margin-left:auto;font-weight:400}
.res ol{list-style:none}
.res li{display:flex;gap:.5rem;align-items:baseline;font-size:.82rem;
 padding:.28rem 0;border-bottom:1px dotted var(--linea);line-height:1.3}
.res li em{font-style:normal;flex:1;min-width:0}
.res li a{color:inherit;text-decoration:none}
.res li a:hover{color:var(--verde-h);text-decoration:underline;text-underline-offset:2px}
.res li small{font-size:.7rem;color:var(--gris);display:block}
.res .n{font-size:.76rem;white-space:nowrap}
.sube{color:var(--m-muy)} .baja{color:var(--verde-h)}
.nota{font-size:.72rem;color:var(--gris);margin-top:.45rem;line-height:1.4}
.aut{font:inherit;background:none;border:0;padding:0;cursor:pointer;
 color:inherit;text-align:left}
.aut:hover{color:var(--verde-h);text-decoration:underline;text-underline-offset:2px}
.tag{font-size:.64rem;border:1px solid currentColor;padding:0 .25rem;
 border-radius:2px;color:var(--oro)}
.react{color:var(--m-muy);border:1px solid currentColor;padding:0 .3rem;
 border-radius:2px;font-size:.68rem}

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
 .res{grid-template-columns:1fr}
 .dlab{font-size:.58rem}
}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*{transition:none!important}}
@media print{
 .tools,.side,.strip,.star,.res{display:none!important}
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

let soloMarcados=false, soloReact=false, temaSel='';

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
  const v=D.filter(d=>{
    if(soloMarcados && !marcados.has(d.url)) return false;
    if(soloReact && !d.reactivado) return false;
    if(temaSel && d.tema!==temaSel) return false;
    if(m && d.animo!==m) return false;
    if(q && !(d.titulo+' '+(d.extracto||'')+' '+d.tema+' '+(d.vecinos||[]).map(v=>v.autor).join(' ')).toLowerCase().includes(q))
      return false;
    return true;});
  /* D llega ordenado del más antiguo al más reciente */
  return $('ord').value==='desc' ? v.reverse() : v;
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
          <span>${d.ultimo_ayto?'última palabra: Ayuntamiento':esc(d.autor)}</span>
          ${d.n_comentarios>1?`<span class="mono">${d.n_comentarios} mensajes · ${d.n_participantes} personas</span>`:''}
          ${d.reactivado?'<span class="react">vuelve a escribir</span>':''}
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
$('ord').onchange=render;
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

/* ── Resumen: cambios, reactivados, autores ── */
function esc(t){return String(t||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function pintarResumen(){
  /* Qué ha cambiado */
  let h1;
  if(!R.n_previas){
    h1=`<p class="nota">Todavía no hay semanas anteriores guardadas.
      La comparativa aparecerá cuando el histórico cubra el período anterior.</p>`;
  }else{
    const t=R.temas.map(x=>({...x,dif:x.ahora-x.antes}))
      .filter(x=>x.dif!==0).sort((a,b)=>Math.abs(b.dif)-Math.abs(a.dif)).slice(0,7);
    h1=t.length?`<ol>`+t.map(x=>`<li><em>${esc(x.tema)}
        ${x.antes===0?'<span class="tag">nuevo</span>':''}
        <small class="mono">media ${R.n_previas} sem.: ${x.media}</small></em>
        <span class="n mono ${x.dif>0?'sube':'baja'}">${x.antes} → ${x.ahora}
        ${x.dif>0?'▲':'▼'}</span></li>`).join('')+`</ol>`
      :`<p class="nota">Sin cambios respecto al período anterior.</p>`;
  }
  /* Vuelven a escribir tras la respuesta */
  const re=D.filter(d=>d.reactivado).sort((a,b)=>b.n_participantes-a.n_participantes
    ||b.n_comentarios-a.n_comentarios);
  const h2=re.length?`<ol>`+re.slice(0,7).map(d=>`<li><em><a href="${d.url}"
      target="_blank" rel="noopener">${esc(d.titulo)}</a>
      <small>${esc(d.tema)} · ${esc(d.autor)}</small></em>
      <span class="n mono">${d.n_comentarios} msj</span></li>`).join('')+`</ol>`
    :`<p class="nota">Nadie ha vuelto a escribir tras una respuesta municipal.</p>`;
  /* Quién escribe más */
  const au=R.autores.slice(0,8);
  const top3=R.autores.slice(0,3).reduce((s,x)=>s+x.mensajes,0);
  const h3=au.length?`<ol>`+au.map(x=>`<li><em><button class="aut" data-a="${esc(x.autor)}"
      title="Ver sus mensajes">${esc(x.autor)}</button>
      <small>${x.asuntos} asunto${x.asuntos>1?'s':''}${x.semanas_previas?
        ` · también en ${x.semanas_previas} sem. anterior${x.semanas_previas>1?'es':''}`:''}</small></em>
      <span class="n mono">${x.mensajes}</span></li>`).join('')+`</ol>
      <p class="nota">Los 3 primeros suman el ${Math.round(top3/Math.max(1,R.total_mensajes)*100)}%
      de ${R.total_mensajes} mensajes de vecinos. Muchos firman con iniciales:
      dos personas distintas pueden coincidir.</p>`
    :`<p class="nota">Sin mensajes de vecinos en el período.</p>`;

  $('res').innerHTML=
    `<div><h2>Qué ha cambiado<b>vs. período anterior</b></h2>${h1}</div>
     <div><h2>Vuelven a escribir<b class="mono">${re.length}</b></h2>${h2}
       ${re.length?`<p class="nota"><button class="aut" id="btnReact">
         ${soloReact?'Ver todos los comentarios':'Ver solo estos en la lista'}</button></p>`:''}</div>
     <div><h2>Quién escribe más<b class="mono">${R.autores.length} autores</b></h2>${h3}</div>`;
  $('res').querySelectorAll('.aut[data-a]').forEach(b=>b.onclick=()=>{
    $('q').value=b.dataset.a; render();});
  if($('btnReact')) $('btnReact').onclick=()=>{soloReact=!soloReact; pintarResumen(); render();};
}

pintarStrip(); pintarTemas(); pintarResumen(); render();
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
    <select id="ord" aria-label="Ordenar por fecha">
      <option value="asc">Del más antiguo al más reciente</option>
      <option value="desc">Del más reciente al más antiguo</option>
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
    <section class="res" id="res" aria-label="Resumen de la semana"></section>
    <div id="lista"></div>
    <footer class="pie">
      Actualizado el {generado}. Los datos proceden del Buzón Ciudadano
      del Ayuntamiento de Vitoria-Gasteiz; cada título enlaza al comentario original.
    </footer>
  </div>
</main>

<script>
const D={payload};
const R={payload_r};
{js}
</script>
</body>
</html>"""


if __name__ == "__main__":
    main()
