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
from scrape import fetch, PAUSA

# ── Preguntas ─────────────────────────────────────────────────────────────────

NO_SI = lambda no, si: {"false": no, "true": si}

PREGUNTAS = {
    "tipo": {
        "type": "choice",
        "instructions": "¿Qué hace el vecino en este mensaje al Ayuntamiento?",
        "criteria": {
            "aviso":          "Avisa de un desperfecto, avería o incidencia concreta para que la arreglen",
            "queja":          "Se queja de un servicio, una norma o una decisión municipal",
            "propuesta":      "Propone una mejora o una idea nueva",
            "pregunta":       "Pregunta algo o pide información",
            "agradecimiento": "Agradece o felicita",
        },
    },
    "lugar": {
        "type": "noul",
        "instructions": "¿Menciona una calle, plaza, barrio, parque o lugar concreto de la ciudad?",
        "criteria": NO_SI("No menciona ningún lugar concreto",
                          "Menciona un lugar concreto de la ciudad"),
    },
    "historia": {
        "type": "noul",
        "instructions": "¿Cuenta un caso concreto con historia, con detalles que se podrían contar en la radio?",
        "criteria": NO_SI("Es un aviso breve o genérico, sin historia",
                          "Cuenta una situación personal o vecinal con detalles"),
    },
    "persiste": {
        "type": "noul",
        "instructions": "¿Dice que el problema persiste, se repite o sigue sin solución después de avisar?",
        "criteria": NO_SI("Es un problema nuevo o puntual",
                          "El problema persiste, se repite o sigue sin arreglarse"),
    },
    "curioso": {
        "type": "noul",
        "instructions": "¿Es curioso, insólito o gracioso, algo que llama la atención o hace sonreír?",
        "criteria": NO_SI("Es un asunto corriente",
                          "Es curioso, insólito o gracioso"),
    },
    "mucha_gente": {
        "type": "noul",
        "instructions": "¿Afecta a mucha gente: un barrio entero, un servicio básico o una decisión polémica?",
        "criteria": NO_SI("Afecta a pocas personas o a un punto aislado",
                          "Afecta a mucha gente o a toda la ciudad"),
    },
}
CRITERIOS = ["historia", "persiste", "curioso", "mucha_gente"]
MAX_CHARS = 3000   # recorte del hilo (Julia admite más, pero no hace falta)

# ── Texto del hilo ────────────────────────────────────────────────────────────

def texto_plano(fragmento):
    t = re.sub(r"<[^>]+>", " ", fragmento)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()

def hilo(html_pag):
    """[(quien, texto)] de todos los mensajes del hilo, en orden."""
    out = []
    for m in re.finditer(r'<li(\s+class="respuesta")?\s+id="CM\d+">([\s\S]*?)</li>', html_pag):
        cuerpo = re.sub(r'<p class="pie">[\s\S]*?</p>', "", m[2])
        cuerpo = re.sub(r'<p id="DOC\d+">[\s\S]*?</p>', "", cuerpo)
        out.append(("Ayuntamiento" if m[1] else "Vecino", texto_plano(cuerpo)))
    return out

def estado(a, mensajes):
    partes = [f"Tema: {a['tema']}", f"Título: {a['titulo']}"]
    partes += [f"{quien}: {txt}" for quien, txt in mensajes] or [f"Vecino: {a['extracto']}"]
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
                   if datetime.fromisoformat(a["fecha"]) >= ini}.values())
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
                "texto": " / ".join(t for q, t in mensajes if q == "Vecino") or a["extracto"]}
        try:
            t1 = time.time()
            r = engine.predict(state=st, questions=PREGUNTAS)["answers"]
            t_julia += time.time() - t1
            fila["tipo"] = r["tipo"]["choice"]
            fila["tipo_p"] = round(max(r["tipo"]["probabilities"].values()), 2)
            for q in ["lugar"] + CRITERIOS:
                fila[q] = round(float(r[q]["probabilities"]["true"]), 2)
            fila["interes"] = round(sum(fila[q] for q in CRITERIOS), 2)
        except Exception as e:
            errores.append(f"{a['url']}: julia: {type(e).__name__}: {e}")
        filas.append(fila)
        if i % 50 == 0:
            print(f"  {i}/{len(semana)}")

    ok = [f for f in filas if "tipo" in f]
    Path("informes").mkdir(exist_ok=True)
    campos = ["fecha", "tema", "titulo", "tipo", "tipo_p", "lugar"] + CRITERIOS + \
             ["interes", "reactivado", "participantes", "url", "texto"]
    with open("informes/julia-prueba.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)

    corto = lambda t, n=280: (t[:n] + "…") if len(t) > n else t
    def ficha(f):
        crit = ", ".join(f"{q} {f[q]:.2f}" for q in CRITERIOS)
        return (f"- **[{f['titulo']}]({f['url']})** · {f['tema']}"
                f"{' · vuelve a escribir' if f['reactivado'] else ''}\n"
                f"  - *{f['tipo']}* ({f['tipo_p']:.2f}) · lugar {f['lugar']:.2f} · {crit} · "
                f"**interés {f['interes']:.2f}**\n"
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
    L += ["", "## Criterios de interés (asuntos con probabilidad > 0,5)\n"]
    L += [f"- {q}: {sum(1 for f in ok if f[q] > 0.5)}" for q in ["lugar"] + CRITERIOS]
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
