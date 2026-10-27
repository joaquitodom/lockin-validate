# lockin-validate (resumen en castellano)

**Herramienta local y sin conexión para validar estrategias cuantitativas de inversión y sus backtests.** Recibe una
carpeta con lo que entrega quien diseñó la estrategia (precios, señales, operaciones, posiciones, costos, reglas,
resultados declarados y, si los hay, fundamentals, universo histórico, registro de pruebas) y produce un informe
reproducible donde **cada hallazgo está vinculado a su evidencia** (líneas del CSV, fechas, valores y procedimiento).

Cada resultado tiene un estado: `CONFIRMED_ERROR` (probado con los insumos), `NEEDS_REVIEW` (lo tiene que mirar una
persona), `NOT_EXECUTABLE` (falta un insumo, y dice cuál) o `PASS` (correcto dentro del alcance del control). Nunca
dice PASS de algo que no pudo verificar.

Controla: calidad de datos (duplicados, fechas imposibles con calendario NYSE / BYMA / ninguno, cobertura, precios
congelados, saltos con forma de split, eventos corporativos, exactitud contra una referencia, point-in-time de
fundamentals, supervivencia, reciclaje de tickers); reconstrucción de posiciones, efectivo y NAV desde las operaciones y
conciliación contra lo declarado (base del retorno = efectivo inicial); información futura; costos omitidos; errores
de métricas por convención; reglas declaradas contra implementación; y estadística (error estándar del Sharpe, ajuste
de Lo 2002, PSR, MinTRL, Deflated Sharpe, haircut por pruebas múltiples, PBO y riesgo de look-ahead en LLMs).

## Uso rápido

```bash
uv sync
uv run lockin-validate run examples/quickstart_inputs --out revision_salida/
uv run lockin-validate init mi_estrategia/     # plantilla de insumos
uv run lockin-validate cases                   # batería de casos sintéticos
```

## Lo que NO hace

No dice si una estrategia es buena ni si va a ganar plata; no es asesoramiento, ni certificación, ni una aprobación
profesional independiente. No baja datos, no usa IA remota ni manda telemetría. No corrige datos en silencio.

Todo el código, la documentación y los informes están en inglés; la especificación completa está en `docs/`.
Licencia Apache-2.0 (Joaquín Domínguez y Mateo Domínguez, 2026). Un futuro servicio web será AGPL-3.0, en un
repositorio aparte.
