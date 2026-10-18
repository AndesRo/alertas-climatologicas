# Despliegue en GitHub y Vercel

Un solo proyecto de Vercel sirve el frontend (estático) y la API (función Python) en el mismo dominio. Costo: $0 en el plan gratuito. No necesitas base de datos ni otros servicios.

Tiempo estimado: 30 a 40 minutos, la mayor parte esperando a que la DMC te entregue credenciales (si decides usarlas).

## 0. Antes de subir: pruébalo en tu máquina

```bash
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest -q                          # deben pasar los 78 tests
python -m scripts.live_check       # consulta las APIs reales
```

`live_check` es la prueba más importante: confirma que Open-Meteo, USGS y el CSN responden desde tu red y muestra las alertas que se generarían ahora. Si una fuente falla, imprime cuál y por qué. Resuelve eso antes de seguir.

## 1. Registrarte en la DMC (opcional, gratis)

Sin esto el sitio funciona igual; solo falta el bloque "Observado por la DMC" en el detalle de cada ciudad.

1. Crea tu cuenta en <https://climatologia.meteochile.gob.cl/application/usuario/registroUsuario> (correo, nombre, institución, clave, ámbito).
2. Inicia sesión y busca tu **token personal** de los servicios web. La documentación pública que pude leer no explica dónde se muestra; si no lo encuentras, escribe a la DMC desde el contacto del portal.
3. Prueba que sirve, con las credenciales solo en tu terminal:

   ```bash
   cd backend
   DMC_USER=tu@correo.cl DMC_TOKEN=tu_token python -m scripts.live_check
   ```

   Debe aparecer `[  OK  ] DMC` y "Ciudades con observación de la DMC: N". Esta integración se escribió según la documentación, sin poder probarla con una cuenta real: este es el momento de confirmarla. Si falla con `HTTP 401` o `403`, el usuario o el token están mal; con otro error, abre un issue con el mensaje exacto.

El token es personal: no lo escribas en el código, en el README ni en un commit.

## 2. Subir el proyecto a GitHub

Desde la carpeta raíz del proyecto (la que contiene `vercel.json`):

```bash
git init -b main
git add .
git commit -m "Centinela: alertas de clima y sismos para Chile"
```

Con la CLI de GitHub (la forma más corta):

```bash
gh auth login                      # solo la primera vez
gh repo create centinela --public --source=. --push
```

O sin ella: crea un repositorio vacío en <https://github.com/new> (sin README ni .gitignore) y ejecuta:

```bash
git remote add origin https://github.com/TU_USUARIO/centinela.git
git push -u origin main
```

Revisa que el repositorio **no** incluya `.env`, `node_modules` ni `dist` (el `.gitignore` ya los excluye). En la pestaña **Actions** debería correr el workflow *CI* y quedar en verde.

## 3. Importar el repositorio en Vercel

1. Entra a <https://vercel.com/new> e inicia sesión con GitHub.
2. Importa el repositorio `centinela`.
3. Deja **Root Directory** en `./`. En **Framework Preset** elige **Other**. Los comandos de build ya están en `vercel.json`; no los cambies.
4. Abre **Environment Variables** y, si hiciste el paso 1, agrega:

   | Nombre | Valor |
   |---|---|
   | `DMC_USER` | tu correo registrado en la DMC |
   | `DMC_TOKEN` | tu token |

   No hace falta ninguna más. `CACHE_TTL_S` (segundos de caché, 600 por defecto) es opcional.
5. Pulsa **Deploy**. La primera vez tarda 1 a 2 minutos.

Desde ahí, cada `git push` a `main` redespliega solo, y cada rama o pull request genera una URL de prueba.

## 4. Verificar que quedó bien

Reemplaza `TU-PROYECTO` por tu dominio de Vercel:

| Qué abrir | Qué debes ver |
|---|---|
| `https://TU-PROYECTO.vercel.app/api/health` | `{"status":"ok"}` |
| `https://TU-PROYECTO.vercel.app/api/overview` | Un JSON grande. Revisa `"sources"`: cada fuente con `"ok": true` (la DMC con `"enabled": false` si no cargaste credenciales) |
| `https://TU-PROYECTO.vercel.app/api/precip` | Un JSON de ~27 kB con `cells` (196 celdas) y `times` (25 horas). La primera vez tarda unos segundos |
| `https://TU-PROYECTO.vercel.app/docs` | La documentación interactiva de la API |
| `https://TU-PROYECTO.vercel.app/` | El mapa, con el estado "Datos de hace N min" arriba a la izquierda |

La primera visita tras un rato de inactividad tarda unos segundos (la función arranca y consulta las fuentes). Las siguientes salen del caché del CDN.

Para comprobar el caché: `curl -sI https://TU-PROYECTO.vercel.app/api/overview` debe mostrar `cache-control: public, max-age=60, s-maxage=600, stale-while-revalidate=3600` y, tras la segunda petición, `x-vercel-cache: HIT`.

## 5. Mantener los datos frescos (opcional)

El workflow `warm.yml` visita `/api/overview` y `/api/precip` cada 20 minutos para que el caché se renueve antes de que llegue alguien. El sitio funciona sin él.

1. En GitHub: **Settings > Secrets and variables > Actions > pestaña Variables > New repository variable**.
2. Nombre `SITE_URL`, valor `https://TU-PROYECTO.vercel.app` (sin barra final).
3. En **Actions > Mantener datos frescos > Run workflow** puedes lanzarlo a mano para probarlo.

GitHub desactiva los workflows programados tras 60 días sin actividad en el repositorio: si lo notas, reactívalo desde la pestaña Actions.

## 6. Dominio propio (opcional)

En Vercel: **Settings > Domains**. Si el dominio es nuevo, Vercel indica los registros DNS que debes crear.

## Si algo falla

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| El build falla en `npm ci` | Falta `frontend/package-lock.json` en el repositorio | Hazlo con `npm install` en `frontend/` y sube el archivo |
| `/api/overview` da 500 | La función no encuentra el código | En Vercel: **Deployments > el despliegue > Functions > logs**. Si dice `ModuleNotFoundError: app`, revisa que `vercel.json` tenga `includeFiles` apuntando a `backend/app/**` |
| `/api/overview` da 503 | Open-Meteo y USGS no respondieron | Es temporal. Se reintenta solo; revisa las páginas de estado de ambos |
| `"ok": false` en la DMC con `HTTP 401` o `403` | Usuario o token incorrectos | Revisa las variables en **Settings > Environment Variables** y vuelve a desplegar (los cambios de variables no se aplican a despliegues ya hechos) |
| La DMC aparece con `"enabled": false` | No se cargaron las variables, o no se redesplegó | Igual que arriba |
| El mapa se ve sin fondo | Las teselas de OpenStreetMap no cargan | Abre las herramientas del navegador (F12 > Network) y mira las peticiones a `tile.openstreetmap.org` |
| `Function timeout` en los logs | Una fuente tardó demasiado | El servicio ya corta a los 25 s y sigue con las demás. Si es recurrente, revisa cuál fuente en `"sources"` |

## Límites del plan gratuito

- Con el caché del CDN, la función se ejecuta aproximadamente una vez cada 10 minutos por región, más las visitas "en frío". Queda muy por debajo de las cuotas del plan gratuito.
- Vercel limita el plan gratuito a uso personal y no comercial, igual que varias de las fuentes de datos.
- Si cambias a un plan de pago o monetizas el sitio, revisa los términos de Open-Meteo, Gael Cloud y RainViewer.
