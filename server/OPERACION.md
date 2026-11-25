# Backend Nosotros (stdlib)

Python 3.11+; sin dependencias externas. Comandos desde la raíz del proyecto:

```sh
python server/crear-usuario usuario
python server/app.py
python server/backup.py
python server/importar_respaldo.py respaldo.json
python -m unittest discover -s server -v
```

`crear-usuario` usa getpass y confirma la contraseña (10–1024 caracteres), o `--password-stdin` para automatización. No acepta contraseña en argumentos. Hay como máximo dos cuentas y un hogar compartido. La API no registra usuarios. `Store.revoke_sessions(username)` permite revocación administrativa.

Variables: `NOSOTROS_PORT` (8787), `NOSOTROS_DATA` (raíz/data), `NOSOTROS_UPLOADS` (raíz/uploads), `NOSOTROS_BACKUPS` (raíz/respaldos). **En producción configurar los tres directorios fuera del repositorio**, con acceso exclusivo del usuario del servicio. Todos los CLI aceptan `--data`, `--uploads`, `--backups`; el servidor además `--host` y `--port`. Escucha 127.0.0.1 por defecto. Usar proxy HTTPS en producción: la cookie Secure no se degrada a HTTP. chmod se aplica con 0700/0600; en Windows además se necesitan ACL adecuadas.

## HTTP

- Públicos: `GET /api/health`, `POST /api/login`, y archivos estáticos explícitos. La SPA pública no contiene datos del hogar.
- `POST /api/login`: `{username,password}`, cookie `__Host-nosotros` HttpOnly/Secure/SameSite=Lax, 90 días.
- `GET /api/session`: `{username}` o 401. `POST /api/logout` revoca el token.
- Todas las mutaciones, incluyendo login, exigen `X-Nosotros-App: 1` y `Origin` con host idéntico a `Host`. Un proxy conectado por loopback puede pasar `X-Forwarded-Host`; no se confía en ese encabezado desde otros peers. No hay CORS.
- `POST /api/sync`: `{since,changes:[{kind,id,payload,updated_at,deleted_at}]}`. `GET /api/sync?since=0`: lectura. Respuesta `{cursor,changes,accepted,server_time}`. Fechas en epoch-ms. `accepted` contiene `{kind,id,updated_at}` sólo para cambios ganadores. Cursor mayor al actual produce 409. Límite 8 MiB / 2000 cambios; validación previa y transacción única.
- Kinds: `events`, `ideas`, `photos`, `collages`, `days`, `notes`, `settings`. Todos los payloads son objetos; tombstones conservan un objeto (puede ser `{}`). Collage usa ID `main`; `slots` acepta objeto original o array. Days: `{meet:boolean,note:string}`; notes: `{text:string}`; settings: `{theme:string}`. Los demás campos se preservan. Timestamp mayor gana; a igual timestamp gana el tombstone, luego desempate estable por contenido.
- `POST` o `PUT /api/photos/{id}`: `{image:'data:image/jpeg;base64,...'}` o PNG; devuelve `{ok:true,url:'/uploads/id'}`. Límite 3 MiB decodificado / 4 MiB base64, firma y dimensiones verificadas sin Pillow. WebP no admitido. Los blobs son archivos de contenido inmutable, reemplazados atómicamente por hash; `GET /uploads/id` autenticado resuelve ID estable mediante SQLite. Metadata usa sync; metadata sin blob se acepta y su imagen devuelve 404 hasta cargarse.

## Respaldos e importación

La app ejecuta un daemon `backup.daily` al arrancar y cada 24 horas, con deduplicación por día UTC; `backup.py --daily` usa la misma política y sin opción genera uno manual. Conserva siete tar.gz en total. SQLite backup API y bloqueo de escritura coordinan una instantánea consistente con uploads. Un faltante cancela el respaldo, no genera un archivo incompleto.

**Los tar.gz contienen usuarios, hashes de contraseña y sesiones; no están cifrados.** Nunca publicarlos ni subirlos a Git. Guardarlos en almacenamiento privado/cifrado. El modo 0600 no reemplaza el cifrado ni las ACL de Windows. Restaurar un tar operativo requiere detener el servicio y reemplazar SQLite/imagenes como conjunto; el CLI `importar_respaldo.py` es exclusivamente para el JSON de exportación de la SPA, no para archivos tar.

La importación v1 preserva IDs, objetos de fotos/encuadres y slots. Convierte notas de texto a `{text}` y completa días históricos con `meet:false,note:''`. Registra SHA-256 del documento canónico; reimportarlo no duplica. Una importación inválida no modifica registros; un fallo del sistema de archivos puede dejar blobs huérfanos inofensivos (sin referencia en SQLite).

Pruebas usan exclusivamente TemporaryDirectory y servidor efímero. No crean usuarios ni datos en las rutas operativas del proyecto.
