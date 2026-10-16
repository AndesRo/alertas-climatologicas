# Publicación en LinkedIn: Centinela

## Antes de publicar (30 minutos)

1. **Despliega** frontend y backend (ver README, sección Despliegue) y confirma que la URL abre sin errores desde el celular.
2. **Corre una vez** `python -m scripts.live_check` con internet. Si responde OK, el ingestor funciona con las APIs reales.
3. **Graba el GIF de 15 segundos con el modo demo** (`python -m scripts.seed_demo`), porque con clima real puede no haber alertas. Guion:
   - Mapa completo con los marcadores latiendo (2 s).
   - Clic en una alerta roja de la lista: el mapa viaja a Punta Arenas (3 s).
   - Se abre el detalle, cambias entre Viento, Lluvia y Temperatura (5 s).
   - Activas y desactivas el radar y los sismos (3 s).
   - Vuelves al mapa general (2 s).
   Herramientas: ScreenToGif (Windows), Kap (Mac) o Peek (Linux). Tamaño máximo recomendado: 8 MB.
4. **Captura 2 imágenes fijas**: el mapa con alertas y el detalle con el gráfico. LinkedIn muestra mejor un carrusel o un video corto que un GIF pesado; sube el GIF como video MP4 si te lo permite.
5. **Pega el GIF en el README** (`docs/demo.gif`) y descomenta la línea de la imagen.
6. **Fija el repositorio** en tu perfil de GitHub y agrega la demo a la sección "Destacados" de LinkedIn.

## Texto del post

> Reemplaza los corchetes. Si algo de lo que dice no es cierto para tu versión final, cámbialo: es mejor un post modesto y verdadero que uno inflado.

Construí Centinela: un panel que vigila el clima y los sismos en 19 ciudades de Chile y avisa cuando algo cruza un umbral.

Lo que más me interesaba no era el mapa sino el recorrido completo de un dato: llega de una API, se evalúa con reglas propias, se guarda y se muestra a alguien que necesita decidir rápido.

Cómo funciona:
→ Un backend en Python (FastAPI) consulta Open-Meteo y USGS cada 15 minutos
→ Un motor de reglas convierte el pronóstico de las próximas 24 horas en alertas amarilla, naranja o roja
→ Una app en React y TypeScript las muestra en un mapa con radar de lluvia, sismos y gráficos por hora

Tres decisiones de las que aprendí:
1. El navegador nunca llama a las APIs externas. El backend las consulta una vez y todos los usuarios leen esa copia. Así respeto los límites gratuitos sin importar cuántas personas entren.
2. El motor de reglas es código puro, sin red ni base de datos. Por eso lo cubrí con tests y pude cambiar umbrales sin miedo.
3. Cada fuente puede fallar sin tumbar a las demás. Si USGS se cae, el clima sigue actualizándose y la interfaz lo avisa.

Un detalle de honestidad: no es un sensor físico, es un sensor virtual. Las alertas son informativas y no reemplazan a SENAPRED ni a la DMC. Lo dejé escrito en la propia app.

Stack: Python · FastAPI · React · TypeScript · Tailwind · Leaflet · SQLite · Docker · GitHub Actions
Todo con APIs gratuitas y costo cero de infraestructura.

Demo: [URL]
Código: [URL del repositorio]

Mi siguiente paso es sumar un sensor real con ESP32 que alimente el mismo panel. Si tienes ideas o ves algo que mejorar, te leo.

#Python #React #TypeScript #FastAPI #DesarrolloWeb #Chile

## Primer comentario (publícalo tú mismo)

Si quieres ver cómo está armado el motor de reglas, está en `backend/app/rules.py` con sus tests en `backend/tests/test_rules.py`: [URL directa al archivo].

## Qué esperar de los reclutadores

Suelen abrir primero la demo y después el README. Por eso el README abre con la demo, explica la arquitectura en un diagrama y deja claras las decisiones y limitaciones. Revisa que los dos enlaces del post funcionen antes de publicar.
