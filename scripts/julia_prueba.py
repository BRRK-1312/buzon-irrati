#!/usr/bin/env python3
"""
Prueba de Julia 1 sobre el Buzón Ciudadano (no toca la página publicada).
Lee la última semana de data/, abre cada hilo, le hace a Julia las preguntas
de abajo y escribe informes/julia-prueba.md y informes/julia-prueba.csv.
Uso: python scripts/julia_prueba.py RUTA_MODELO
"""
import csv, html, json, random, re, sys, time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from scrape import fetch, PAUSA, TRASLADO

# ── Preguntas ─────────────────────────────────────────────────────────────────
# Versión 2. En la v1 las preguntas de sí/no salían "sí" casi siempre (sin
# contraste) y "pregunta" se comía muchas quejas y avisos. Ahora las opciones
# compiten entre sí, y el interés incluye una opción "rutinario".

PREGUNTAS = {
    "tipo": {
        "type": "choice",
        "instructions": "¿Qué hace el vecino en su mensaje al Ayuntamiento?",
        "criteria": {
            "aviso":          "Comunica un desperfecto o problema físico concreto en un sitio "
                              "(farola fundida, bache, bolardo roto, contenedor, suciedad, árbol) "
                              "para que lo arreglen",
            "queja":          "Protesta por cómo funciona un servicio, una norma, un trato recibido "
                              "o molestias que se repiten (autobuses, ruido, terrazas, obras, multas)",
            "propuesta":      "Sugiere crear o cambiar algo que hoy no existe "
                              "(un paso de peatones, más bancos, otro horario, una zona nueva)",
            "pregunta":       "Solo pide información o una explicación, sin denunciar ningún problema",
            "agradecimiento": "Agradece o felicita al Ayuntamiento o a un servicio",
        },
    },
    "interes": {
        "type": "choice",
        "instructions": "Para un programa de radio sobre el buzón ciudadano, "
                        "¿qué tiene de especial este mensaje?",
        "criteria": {
            "rutinario":   "Nada especial: un aviso o petición corriente de los que llegan a diario",
            "historia":    "Cuenta un caso personal o vecinal con detalles, una historia que se puede contar",
            "persiste":    "El problema sigue sin resolverse tras avisar varias veces o lleva meses así",
            "curioso":     "Es curioso, insólito o gracioso, algo que sorprende o hace sonreír",
            "mucha_gente": "Afecta a un barrio entero, a un servicio que usa mucha gente "
                           "o a una decisión municipal polémica",
        },
    },
}
MOTIVOS = ["historia", "persiste", "curioso", "mucha_gente"]
MAX_CHARS = 3000   # recorte del hilo (Julia admite más, pero no hace falta)

# ── Texto del hilo ────────────────────────────────────────────────────────────

def texto_plano(fragmento):
    t = re.sub(r"<[^>]+>", " ", fragmento)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()

def hilo(html_pag):
    """[(quien, texto)] de todos los mensajes del hilo, en orden."""
    out = []
    for m in re.finditer(r'<li(?:\s+class="([^"]*)")?\s+id="CM\d+">([\s\S]*?)</li>', html_pag):
        cuerpo = re.sub(r'<p class="pie">[\s\S]*?</p>', "", m[2])
        cuerpo = re.sub(r'<p id="DOC\d+">[\s\S]*?</p>', "", cuerpo)
        out.append(("Ayuntamiento" if "respuesta" in (m[1] or "") else "Vecino",
                    texto_plano(cuerpo)))
    return out

def estado(a, mensajes):
    # Solo lo que escriben los vecinos: las respuestas municipales son fórmulas
    # ("Personal encargado se dirigirá…") que confunden al modelo.
    vecinos = [txt for quien, txt in mensajes if quien == "Vecino"] or [a["extracto"]]
    partes = [f"Título: {a['titulo']}", f"Tema: {a['tema']}"]
    partes += [f"Vecino: {t}" for t in vecinos]
    n_ayto = sum(1 for quien, _ in mensajes if quien == "Ayuntamiento")
    if n_ayto:
        partes.append(f"(El Ayuntamiento ha respondido {n_ayto} vez/veces.)")
    s = "\n".join(partes)
    return s if len(s) <= MAX_CHARS else s[:MAX_CHARS // 2] + "\n[…]\n" + s[-MAX_CHARS // 2:]

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ruta_modelo = sys.argv[1] if len(sys.argv) > 1 else "Julia-1"
    hist = []
    for f in sorted(Path("data").glob("????-W??.json")):
        hist += json.loads(f.read_text(encoding="utf-8"))
    if not hist:
        sys.exit("No hay datos en data/: ejecuta antes 'Actualizar Buzón'.")
    fin = max(datetime.fromisoformat(a["fecha"]) for a in hist)
    ini = fin - timedelta(days=7)
    semana = list({a["url"]: a for a in hist
                   if datetime.fromisoformat(a["fecha"]) >= ini
                   and not a["extracto"].startswith(TRASLADO)}.values())
    print(f"{len(semana)} asuntos entre {ini:%d/%m} y {fin:%d/%m}")

    from julia import load_model
    t0 = time.time()
    engine = load_model(ruta_modelo, device="cpu", strict_encoding=True,
                        max_length=8192, head_length=512)
    t_carga = time.time() - t0

    filas, errores, t_julia = [], [], 0.0
    for i, a in enumerate(semana, 1):
        try:
            mensajes = hilo(fetch(a["url"]))
            time.sleep(PAUSA)
        except Exception as e:
            mensajes = []
            errores.append(f"{a['url']}: descarga: {e}")
        st = estado(a, mensajes)
        fila = {"fecha": a["fecha"], "tema": a["tema"], "titulo": a["titulo"], "url": a["url"],
                "reactivado": a.get("reactivado", False),
                "participantes": a.get("n_participantes", 1),
                "texto": (" / ".join(t for q, t in mensajes if q == "Vecino") or a["extracto"])[:1500]}
        try:
            t1 = time.time()
            r = engine.predict(state=st, questions=PREGUNTAS)["answers"]
            t_julia += time.time() - t1
            fila["tipo"] = r["tipo"]["choice"]
            fila["tipo_p"] = round(max(r["tipo"]["probabilities"].values()), 2)
            pi = r["interes"]["probabilities"]
            for q in ["rutinario"] + MOTIVOS:
                fila[q] = round(float(pi[q]), 2)
            fila["motivo"] = max(MOTIVOS, key=lambda q: pi[q])
            fila["interes"] = round(1 - float(pi["rutinario"]), 2)
        except Exception as e:
            errores.append(f"{a['url']}: julia: {type(e).__name__}: {e}")
        filas.append(fila)
        if i % 50 == 0:
            print(f"  {i}/{len(semana)}")

    ok = [f for f in filas if "tipo" in f]
    Path("informes").mkdir(exist_ok=True)
    campos = ["fecha", "tema", "titulo", "tipo", "tipo_p", "interes", "motivo", "rutinario"] + \
             MOTIVOS + ["reactivado", "participantes", "url", "texto"]
    with open("informes/julia-prueba.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)

    corto = lambda t, n=280: (t[:n] + "…") if len(t) > n else t
    def ficha(f):
        return (f"- **[{f['titulo']}]({f['url']})** · {f['tema']}"
                f"{' · vuelve a escribir' if f['reactivado'] else ''}\n"
                f"  - *{f['tipo']}* ({f['tipo_p']:.2f}) · **interés {f['interes']:.2f}**"
                f" · motivo: {f['motivo']} ({f[f['motivo']]:.2f})\n"
                f"  - > {corto(f['texto'])}\n")

    L = [f"# Prueba de Julia 1 · {ini:%d/%m} – {fin:%d/%m/%Y}\n",
         f"Generado el {datetime.now():%d/%m/%Y %H:%M}. Asuntos: {len(semana)}, "
         f"clasificados: {len(ok)}, errores: {len(errores)}.\n",
         f"Tiempo: carga del modelo {t_carga:.0f} s, clasificación {t_julia:.0f} s "
         f"({t_julia / max(1, len(ok)):.2f} s por asunto).\n",
         "## Reparto por tipo\n"]
    tipos = {}
    for f in ok:
        tipos[f["tipo"]] = tipos.get(f["tipo"], 0) + 1
    L += [f"- {t}: {n}" for t, n in sorted(tipos.items(), key=lambda x: -x[1])]
    L += ["", "## Reparto del interés\n",
          "Interés = 1 − probabilidad de «rutinario». Sirve si separa: pocos arriba, muchos abajo.\n"]
    tramos = [(0.8, 1.01), (0.6, 0.8), (0.4, 0.6), (0.2, 0.4), (0, 0.2)]
    L += [f"- {a:.1f}–{min(b, 1):.1f}: {sum(1 for f in ok if a <= f['interes'] < b)}" for a, b in tramos]
    L += ["", "Motivo principal entre los 50 más interesantes:\n"]
    top50 = sorted(ok, key=lambda f: -f["interes"])[:50]
    L += [f"- {q}: {sum(1 for f in top50 if f['motivo'] == q)}" for q in MOTIVOS]
    L += ["", "## Top 10 por interés\n"]
    L += [ficha(f) for f in sorted(ok, key=lambda f: -f["interes"])[:10]]
    L += ["## Muestra aleatoria de 40 (para revisar a mano)\n"]
    L += [ficha(f) for f in random.Random(1312).sample(ok, min(40, len(ok)))]
    if errores:
        L += ["## Errores\n"] + [f"- {e}" for e in errores[:30]]
    Path("informes/julia-prueba.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"Informe escrito · {len(ok)} clasificados, {len(errores)} errores")

if __name__ == "__main__":
    main()
