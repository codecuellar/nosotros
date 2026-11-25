# Nuestro rincón ♥

Una web para guardar planes, ideas y recuerdos de a dos. Un único `index.html`, sin instalaciones, cuentas, fuentes externas ni dependencias. Funciona desde GitHub Pages y abriendo el archivo en un navegador moderno.

## Personalizar CONFIG

Abrí `index.html` con un editor de texto. El primer `<script>`, antes de los estilos, contiene `const CONFIG`:

- `nombres`: los dos nombres. El valor inicial es `['Agus', 'Mi amor']`; cambialo por los suyos.
- `bienvenida`: mensaje de entrada. La animación dura entre 5 y 6 segundos y se salta con un toque.
- `tema`: `'auto'`, `'fiestas'` o `'romantico'`. En automático `mesesFiestas: [11,12,1]` activa Navidad/Año Nuevo de noviembre a enero.
- `feriados`: `{fecha:'MM-DD', nombre:'…'}` para fechas anuales y `{fecha:'YYYY-MM-DD', nombre:'…'}` para fechas exactas. Agregá los puentes y traslados oficiales de cada año. Carnaval y Viernes Santo se calculan; los trasladables no confirmados aparecen como **revisar traslado**, no como una fecha oficial inventada.
- `maxFotoPx` y `calidadFoto`: límite y compresión JPEG de las fotos (1200 px y 0.83 por defecto).

Los ajustes de tema elegidos desde la app tienen prioridad sobre CONFIG. Para volver al comportamiento del archivo, seleccioná **Según CONFIG / temporada** en Ajustes.

## Usar y respaldar

- Calendario: navegación mensual sin un límite de año impuesto, encuentros, notas y actividades con categoría, hora y estado. Reemplazar conserva el plan anterior como cancelado; eliminar pide confirmación.
- Planes: seis categorías, enlace opcional, editar/eliminar/completar y asignar al calendario. Completar una idea y completar su actividad son acciones independientes.
- Fotos: carga múltiple, reducción local a 1200 px, marcos Polaroid y leyendas editables. HEIC depende de si el navegador puede decodificarlo; JPG/PNG/WebP son las opciones más compatibles.
- Collage: cinco plantillas (máximo 4 o 5 fotos), selección desde galería o carga nueva, encuadre horizontal/vertical y zoom. Cada plantilla conserva su distribución. Imprimir/Guardar PDF usa una hoja A4 limpia; PNG usa 2480 × 3508 px. Los marcos vacíos se imprimen como ilustraciones, no como botones.
- Ajustes: **Exportar datos completos (.json)** incluye fotos, planes, notas y collages. Pasen ese archivo al otro celular y usen **Importar copia**. Importar reemplaza, no fusiona; primero descarga una copia de los datos locales. Verificá que el navegador haya guardado esa copia antes de seguir. Límite de importación: 100 MB.

**No hay sincronización automática, servidor, autenticación ni cifrado.** Los planes se guardan en localStorage y las imágenes en IndexedDB del navegador. No se suben a GitHub. Si borrás los datos del sitio, cambiás de navegador/dispositivo o usás modo privado podés perderlos: exportá seguido. GitHub Pages y el código son públicos; cualquiera con acceso al perfil del navegador puede abrir los recuerdos locales. No pongas claves o información sensible en CONFIG.

Las fotos y los datos del dominio local y del dominio de GitHub Pages son almacenamientos distintos. Para mudarlos, usá exportar/importar. Los respaldos tienen información privada: no los subas al repositorio.

## Publicación

Repositorio creado y código subido a `main`: https://github.com/codecuellar/nosotros

**GitHub Pages quedó pendiente de activación:** la API de GitHub devolvió HTTP 500 al habilitarlo. Para terminarlo, entrá con tu cuenta en https://github.com/codecuellar/nosotros/settings/pages y elegí **Deploy from a branch → main → / (root) → Save**.

Una vez desplegado, la dirección será https://codecuellar.github.io/nosotros/ (no se presenta como activa hasta que GitHub complete la publicación).

Alternativa con GitHub CLI instalado y autenticado:

```bash
gh api --method POST repos/codecuellar/nosotros/pages -f 'source[branch]=main' -f 'source[path]=/'
```

Para futuras modificaciones, desde esta carpeta:

```bash
git add index.html README.md
git commit -m "Actualizar nuestro rincon"
git push origin main
```

No recrees el repositorio ni uses `push --force`.

`referencia/` contiene copias intactas de los originales y está excluida por `.gitignore`. `.verificacion/` contiene evidencia local de pruebas y tampoco se publica. No se modificaron los archivos originales del directorio padre.
