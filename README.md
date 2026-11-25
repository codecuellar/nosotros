# Nuestro rincón · Agus & Mi amor

Web privada de pareja: calendario, ideas, Polaroids y collages A4. Conserva el diseño romántico original y los temas estacionales. **Ahora necesita el servidor Python: GitHub Pages no ejecuta la API.** No hay servicios externos para datos, registro público ni dependencias Python de terceros.

## Instalación actual

- Moto G6 Plus / Termux, Python 3.14, SQLite; servidor en `~/nosotros`.
- Escucha sólo `127.0.0.1:8787`, detrás de HTTPS Tailscale, sin abrir puertos del router.
- Base, fotos, copias y estado de Tailscale fuera del repo: `~/nosotros-private/`.
- Cuentas `agus` y `amor`, creadas desde terminal, contraseñas sólo como hashes scrypt. El archivo de accesos se entrega privadamente; no se publica.
- Respaldo antiguo importado: **2 actividades, 1 idea y 2 fotos**. Segunda importación no duplica. El JSON original permanece intacto y fuera de GitHub.
- Activación HTTPS pendiente de autorizar el nuevo nodo `nosotros-moto` en la cuenta de su dueño. No se inventa una URL antes de que Tailscale la asigne.

**Guía completa:** [README-SERVIDOR.md](README-SERVIDOR.md): instalación, usuarios, importación, inicio, logs, backups y comandos Serve/Funnel en 443.

## CONFIG

Editar el objeto `CONFIG` al comienzo de `index.html`:

```js
nombres: ['Agus', 'Mi amor'],
bienvenida: 'Hay lugares que no son lugares. Son personas. Y el mío sos vos.',
bienvenidaMs: 5500,
tema: 'auto',
mesesFiestas: [11, 12, 1],
maxFotoPx: 1200,
calidadFoto: 0.85,
```

`feriados` admite fechas `MM-DD` anuales o `AAAA-MM-DD` exactas. Confirmar traslados y puentes cada año. El selector de tema también se comparte como dato de la pareja. Los nombres se configuran en el código; no son los usuarios de login.

## Datos y modo sin conexión

IndexedDB conserva datos, fotos redimensionadas y una cola durable. Al reconectar, al abrir y cada cuatro segundos se envían pendientes y se consultan cambios desde el último cursor. IDs estables + `updated_at` por registro; gana el más reciente. Los borrados conservan `deleted_at`, evitando que reaparezcan por reintentos antiguos.

Fotos JPEG/PNG verificadas en el servidor, máximo **3 MB por foto** después del redimensionado. Todas las rutas de datos y fotos exigen una sesión válida; cookies HttpOnly + Secure + SameSite=Lax, duración 90 días, bloqueo de login tras intentos fallidos. Las fotos offline viven en IndexedDB, no en el caché público del service worker.

PWA: abrir una vez con conexión y login; en Safari usar Compartir → Añadir a pantalla de inicio. **iOS no garantiza sincronización con la aplicación cerrada**; se retoma al abrirla. Con servidor caído puede usarse la copia local de una sesión previamente iniciada. Cerrar sesión revoca el token y borra esa copia; no salir con pendientes sin exportarlos primero. Proteger el celular con código: los datos offline no están cifrados en el navegador.

Ajustes permite exportar/importar JSON y migrar localStorage antiguo del **mismo origen**. Importar incorpora IDs faltantes sin duplicar ni borrar recuerdos actuales. GitHub Pages y el dominio privado tienen almacenamientos distintos: para pasar datos del primero al segundo se usa el JSON, no es posible leer automáticamente almacenamiento de otro dominio. El respaldo de esta instalación ya se migró desde terminal.

## Inicio y mantenimiento

En el Moto:

```bash
cd ~/nosotros
bash server-ops/start.sh start
bash server-ops/start.sh status
# Sólo nuestra app, sin detener las demás:
bash server-ops/start.sh stop
```

Termux:Boot tiene una entrada independiente y tmux supervisa la app cada cinco segundos. Respaldos diarios de SQLite + fotos, conserva los últimos siete. No se reinicia el teléfono para probar Boot porque aloja otras apps. Android aún puede suspender Termux: excluirlo del ahorro de batería y mantener el teléfono conectado.

Logs y copia desde la PC:

```bash
ssh moto 'tail -n 100 -f ~/logs/nosotros.log'
scp -r 'moto:~/nosotros-private/respaldos' './Copias-Nosotros/'
```

La guía del servidor incluye copia manual, restauración segura y configuración HTTPS. Ni el repositorio ni GitHub contienen la base, fotos, contraseñas, JSON privado o estado de Tailscale.

## Verificación

Backend con datos sintéticos aislados:

```bash
python -m unittest discover -s server -p 'test_*.py' -v
```

También se ejercitaron dos sesiones de navegador distintas, evento y foto compartidos, acceso anónimo bloqueado, PWA con servidor de pruebas realmente apagado, cola offline y recuperación automática. Se verificó en el Moto que ambas cuentas leen las dos fotos originales con bytes idénticos al JSON y que cerrar sesión revoca el acceso. Evidencias y herramientas locales se excluyen de Git.

## Archivos y seguridad

`index.html` conserva la presentación; `sync.js` implementa persistencia compartida; `server/` contiene API, administración y copias; `server-ops/` contiene scripts Termux y Tailscale; `manifest.json`, `sw.js` e íconos permiten el arranque offline. La versión anterior está guardada localmente como `respaldo/index-localstorage.html`, fuera del commit. Los originales del directorio padre no se modificaron.

Para instalar desde cero: clonar el repo, seguir la guía de servidor, crear las dos cuentas e iniciar antes de exponer HTTPS. Nunca publicar `data/`, `uploads/`, `.env`, `respaldos/` ni claves de Tailscale. El código es público, los recuerdos no.
