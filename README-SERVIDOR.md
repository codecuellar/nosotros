# Nuestro rincón · servidor Moto / Termux

**Código:** `~/nosotros` (`ROOT`). **Privado, fuera del repo:**
`~/nosotros-private/data`, `~/nosotros-private/uploads`, `~/nosotros-private/respaldos`.
No subir JSON, fotos, usuarios, sesiones, backups ni estado de Tailscale a GitHub.
El despliegue de esta instalación está en `~/nosotros`, probado por SSH en el Moto.
El JSON original fue importado dos veces para verificar idempotencia: 2 actividades, 1 idea y 2 fotos, sin duplicados. Las credenciales están en un archivo privado de la PC, nunca en este repositorio.

## Instalar y arrancar (manualmente en Moto)

```bash
pkg install python tmux curl
cd ~/nosotros
chmod +x server-ops/*.sh
bash server-ops/start.sh start
bash server-ops/start.sh status
```

El backend escucha **sólo `127.0.0.1:8787`**, con `NOSOTROS_PORT=8787`,
`NOSOTROS_HOST=127.0.0.1` y las tres rutas privadas `NOSOTROS_DATA`,
`NOSOTROS_UPLOADS`, `NOSOTROS_BACKUPS`. Las cookies mantienen **Secure**;
HTTP directo sirve para `/api/health`, no para iniciar sesión desde otro equipo.
Usar HTTPS en el navegador; no deshabilitar Secure para probar.

Usuarios: la instalación actual ya tiene `agus` y `amor`. Máximo dos; no hay registro público. Para una instalación nueva, crear desde terminal sin poner contraseñas en argumentos:

```bash
export NOSOTROS_DATA="$HOME/nosotros-private/data"
export NOSOTROS_UPLOADS="$HOME/nosotros-private/uploads"
export NOSOTROS_BACKUPS="$HOME/nosotros-private/respaldos"
python server/crear-usuario agus
python server/crear-usuario amor
```

Importar JSON antiguo sin duplicados:

```bash
python server/importar_respaldo.py /ruta/privada/al/respaldo.json
```

Sólo se crean las sesiones tmux **`nosotros`** y **`nosotros-watch`**. El watchdog
revisa cada 5 s y relanza si cae la app. `bash server-ops/start.sh stop` detiene
solamente esas dos sesiones; no reinicia ningún otro servicio. No usar
`tmux kill-server`, `pkill python` ni modificar `~/servidor.sh`.
Logs: `~/logs/nosotros.log` y `.log.1`, máximo 5 MiB **cada archivo**.
No registrar contraseñas ni cuerpos privados desde el backend.

## Arranque Android independiente

Instalar **Termux:Boot** del mismo origen que Termux y abrirlo una vez. Excluir
Termux y Termux:Boot del ahorro de batería. Android puede matar procesos; esto
no es garantía de disponibilidad 24/7.

```bash
mkdir -p ~/.termux/boot
# No sobrescribir un archivo existente, ni tocar .termux/boot/servidor.
test ! -e ~/.termux/boot/nosotros && \
  cp ~/nosotros/server-ops/termux-boot.sh ~/.termux/boot/nosotros
chmod 700 ~/.termux/boot/nosotros
```

El script pide wake-lock y arranca nuestro watchdog. La VPN Android existente
no se modifica.

## HTTPS 443: Tailscale nativo no equivale a CLI

La [instalación oficial Android](https://tailscale.com/docs/install/android)
es una app VPN; **no instala una CLI `tailscale` utilizable en Termux**.
La Moto no tiene esa CLI. [Funnel exige una plataforma con CLI](https://tailscale.com/docs/features/tailscale-funnel#requirements-and-limitations).
No se puede prometer `serve`/`funnel` dentro de la app Android.

**Alternativa experimental sin root:** binarios Linux estáticos ARM64 y un
`tailscaled --tun=userspace-networking` separado. El
[modo userspace oficial](https://tailscale.com/docs/concepts/userspace-networking)
no necesita `/dev/net/tun`; hacer proxy de un puerto no requiere root. Esto
justifica probarlo, **no certifica compatibilidad con Android 9/Termux**: pueden
fallar syscalls, políticas Android, DNS o conectividad con la VPN nativa.
No desactivar esa VPN ni tocar su estado para resolverlo automáticamente.
El daemon separado se registra como **otro nodo**, no como la app Android.

En este Moto ya se instalaron los binarios oficiales, se inició el daemon y se generó un enlace de autorización. El nodo sigue pendiente de que su dueño complete el login. Para una instalación nueva:

```bash
cd ~/nosotros
python server-ops/setup-tailscale.py --install
bash server-ops/tailscale-userspace.sh start
BASE="$HOME/nosotros-private/tailscale"
TS="$HOME/nosotros/server-ops/ts"
bash "$TS" version
bash "$TS" up --accept-dns=false --hostname=nosotros-moto
# Abrir MANUALMENTE el enlace de login mostrado; no usar auth keys en scripts.
bash "$TS" status
bash "$TS" serve status
# Sólo si la configuración de este nodo está vacía, compartir privado por HTTPS:
bash "$TS" serve --bg --https=443 http://127.0.0.1:8787
```

El instalador obtiene versión estable y archivo ARM64 desde
`https://pkgs.tailscale.com/stable/?mode=json`, valida nombre/versión/origen HTTPS
y SHA256 oficial, instala únicamente en `~/nosotros-private/tailscale/bin` y se
niega a sobrescribirlo. No instala unidades de sistema, no usa sudo, no autentica
ni publica. SHA256 del mismo origen verifica integridad, no una firma separada.
**Particularidad comprobada en Android 9:** ejecutar la CLI con el PATH completo de Termux provoca `SIGSYS` al consultar `termux-clipboard-set` (`faccessat2`). El wrapper `server-ops/ts` limita PATH a `/system/bin` sólo para esa CLI; `bash server-ops/ts version` fue ejecutado con éxito. El daemon sí arrancó con userspace y obtuvo el enlace de autenticación.

Estado/socket propios; tmux opcional **`nosotros-tail`** y logs separados rotados.

[Serve](https://tailscale.com/docs/reference/tailscale-cli/serve) es privado al
tailnet. Activar MagicDNS/HTTPS con la cuenta del usuario y probar la URL exacta
mostrada, sin inventar un dominio. El registro del nodo y **DNS final quedan
pendientes del login y aprobaciones del usuario**. El certificado público revela
el nombre del nodo en registros de transparencia: elegir un nombre no sensible.

**Sólo si se desea público y el login de la app ya fue probado**, ejecutar
manualmente (no está en boot ni setup):

```bash
bash "$TS" funnel --bg --https=443 http://127.0.0.1:8787
bash "$TS" funnel status
# Retirar únicamente nuestro endpoint público:
bash "$TS" funnel --https=443 off
```

[Funnel](https://tailscale.com/docs/reference/tailscale-cli/funnel) publica a
**todo Internet**, requiere MagicDNS, HTTPS y permiso `funnel` en la política.
443/8443/10000 son los puertos permitidos. Serve y Funnel no pueden compartir 443
simultáneamente: el último comando determina si queda privado o público. No
usar `serve reset`, `funnel reset` ni reemplazar políticas de otras aplicaciones.
No publicar directorios, `data`, `uploads` ni backups como archivos estáticos.

Después de comprobar compatibilidad y login, opt-in para relanzar **sólo el daemon**
en boot (las opciones `--bg` de Serve/Funnel quedan persistidas en su estado):

```bash
touch ~/nosotros-private/tailscale/enable-boot
# Deshabilitar ese autoarranque sin tocar VPN/otros nodos:
rm ~/nosotros-private/tailscale/enable-boot
bash ~/nosotros/server-ops/tailscale-userspace.sh stop
```

Si el binario/daemon no funciona en Moto, **HTTPS remoto queda bloqueado** con
este método; usar un host Linux separado con CLI y conectividad privada real al
backend, o un túnel HTTPS autorizado por el usuario. El `127.0.0.1` de ese host
no es la Moto: requiere diseño adicional, no publicar 8787 indiscriminadamente.
No afirmar que la VPN Android por sí sola resuelve Serve/Funnel.

## Copias y recuperación

El backend hace una copia cada 24 h; el watchdog no duplica ese trabajo.
Copia manual (consultar también `--help` si se precisan opciones):

```bash
cd ~/nosotros
NOSOTROS_DATA="$HOME/nosotros-private/data" \
NOSOTROS_UPLOADS="$HOME/nosotros-private/uploads" \
NOSOTROS_BACKUPS="$HOME/nosotros-private/respaldos" python server/backup.py
```

Desde **la PC**, con el alias SSH ya configurado y destino privado, no el repo:

```bash
mkdir -p "$HOME/Copias-Nosotros"
scp -r 'moto:~/nosotros-private/respaldos' "$HOME/Copias-Nosotros/"
```

Las copias contienen información personal; cifrarlas en almacenamiento externo.
Verificar que el backup incluya DB y fotos y probar recuperación en un directorio
separado antes de borrar originales. Nunca sobreescribir una base en ejecución.

## PWA y offline

`manifest.json`, los dos iconos propios y `sw.js` son públicos. El SW sólo cachea
`/`, `/index.html`, `/sync.js`, `/manifest.json`, `/icon-192.png`, `/icon-512.png`.
No intercepta API, uploads, consultas ni rutas ajenas: **no devuelve HTML para
una API offline**. No cachea 401, redirecciones ni respuestas opacas. Navegación
al shell: red primero, fallback a index si falla la red o el proxy devuelve 5xx. Incrementar versión
del caché al cambiar shell. Fotos offline: responsabilidad del frontend mediante
IndexedDB y limpieza al cerrar sesión, nunca CacheStorage. HTTPS es necesario
para instalar y usar el SW fuera de localhost. Los cambios a registro del SW,
manifest en HTML y política IndexedDB se integran en el frontend, no aquí.


## Panel Tailscale y acceso desde iPhone

1. Autorizar el nodo `nosotros-moto` con la cuenta propietaria, sin desactivar la app Android existente. Aprobarlo en Machines si el tailnet exige aprobación.
2. En DNS habilitar MagicDNS y HTTPS Certificates. Elegir un nombre no sensible: el certificado aparece en registros públicos de transparencia.
3. Con Serve, agregar a ambos al tailnet o compartir este nodo desde Machines → Share. Instalar Tailscale en ambos iPhone/celulares y conectar. Las ACL/grants deben permitirles `tcp:443` hacia este nodo.
4. Ejecutar `bash ~/nosotros/server-ops/ts serve --bg --https=443 http://127.0.0.1:8787` y copiar la URL REAL que imprime. No se inventa una dirección antes de autorizar el nodo.
5. Funnel es opcional y hace público el login: habilitar el atributo `funnel` para este nodo en la política y usar el comando anterior de Funnel. No reemplazar la política completa ni tocar otros nodos. No se activó automáticamente.
6. No abrir puertos en el router. Para instalar PWA en iPhone usar Safari con esa URL HTTPS → Compartir → Añadir a pantalla de inicio. iOS sólo sincroniza mientras la app esté abierta o al volver a abrirla; no se promete envío en segundo plano con Safari cerrado.

Para repetir el login si venció el enlace: `bash ~/nosotros/server-ops/ts up --accept-dns=false --hostname=nosotros-moto --timeout=15s`.

### Logs

```bash
ssh moto 'tail -n 100 -f ~/logs/nosotros.log'
# Estado:
ssh moto 'bash ~/nosotros/server-ops/start.sh status'
```

No se reinició Android para probar Boot porque eso detendría las otras apps. Sí se instalaron la entrada de Termux:Boot independiente y el watchdog de esta app.
