# Buzón Ciudadano · Herramienta para radio

Recoge los comentarios del Buzón Ciudadano de Vitoria-Gasteiz de los últimos
días y los publica como página web consultable.

**URL de la herramienta:** `https://TU_USUARIO.github.io/buzon-radio/`

## Puesta en marcha (una vez)

1. Crea un repositorio llamado `buzon-radio` y sube estos archivos.
2. **Settings → Actions → General → Workflow permissions** → marca
   *Read and write permissions* → Save.
3. **Actions → Actualizar Buzón → Run workflow** → Run.
   Tarda unos minutos (recorre todos los temas del buzón).
4. **Settings → Pages** → Source: *Deploy from a branch*, rama `gh-pages`,
   carpeta `/ (root)` → Save.

Tras el primer despliegue la URL queda fija.

## Uso

- **Actualizar cuando quieras:** Actions → Run workflow. Puedes indicar
  cuántos días hacia atrás quieres (7 por defecto).
- **Actualización automática:** cada día a las 8:00. Para desactivarla,
  borra el bloque `schedule` de `.github/workflows/scrape.yml`.

## Cómo funciona

El buzón organiza los comentarios en áreas (Espacio público, Movilidad…) y
dentro de cada una en temas concretos (Alumbrado público, Zonas verdes…).
El script descubre todos los temas automáticamente, recorre sus asuntos y
se detiene al llegar a comentarios más antiguos que el período pedido.

La página resultante agrupa los comentarios por día y permite filtrar por
área, por estado de ánimo y por texto libre.
