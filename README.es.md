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

## Casos de uso (0.3.0)

El núcleo valida el backtest de una estrategia sistemática. La versión 0.3.0 suma seis **módulos de caso de uso**
opcionales para otros tipos de modelos financieros. Todos siguen el mismo contrato que el núcleo (un estado por
resultado, evidencia en cada hallazgo, nunca PASS de algo que no se pudo verificar) y leen sus propias tablas de
entrada (`docs/INPUT_SPEC.md`, sección "Use-case module tables"). Los controles son ayudas para quien revisa el
trabajo: no son una certificación, ni una aprobación, ni una declaración de cumplimiento regulatorio, y no dicen si un
modelo va a ganar plata.

| Módulo | Qué valida | Para quién | Archivos que lo activan | Controles principales |
|---|---|---|---|---|
| [signals](docs/usecases/signals.md) | una señal alfa o factor antes de convertirse en estrategia | investigadores cuantitativos, equipos de factores | `signals.csv` (+ `prices.csv`) | alineación con retornos futuros, IC de rangos con t de Newey-West, spread por cuantiles, rotación y vida media, indicio de look-ahead |
| [ml](docs/usecases/ml.md) | un modelo supervisado usado en finanzas, a partir de su protocolo de muestreo y de las predicciones entregadas (nunca se reentrena) | científicos de datos, equipos de riesgo de modelo | `ml_samples.csv` o `ml_predictions.csv` | fuga entre particiones (solapamiento, purga, embargo), brecha entrenamiento / prueba, calibración (ECE, Hosmer-Lemeshow), PSI, fuga del objetivo, modelos evaluados en prueba |
| [risk](docs/usecases/risk.md) | pronósticos de VaR y Expected Shortfall contra el resultado realizado | gestores de riesgo, unidades de validación de modelos | `var_forecasts.csv` | coherencia de insumos, Kupiec, Christoffersen, semáforo de Basilea, test de ES de Acerbi y Szekely, estabilidad |
| [forecast](docs/usecases/forecast.md) | pronósticos puntuales de una serie financiera o económica | economistas, estrategas, tesorería y FP&A | `forecasts.csv` | integridad del origen, Diebold-Mariano contra ingenuo, sesgo de Mincer-Zarnowitz, dirección de Pesaran-Timmermann, dinámica de errores, varios modelos |
| [portfolio](docs/usecases/portfolio.md) | los pesos objetivo de un modelo de asignación | gestores de cartera, asignadores, comités de inversión, compliance | `weights.csv` | restricciones declaradas, concentración, rotación neta de deriva, pesos contra posiciones, contra 1/N, active share |
| [live](docs/usecases/live.md) | un historial en vivo o de paper trading contra su backtest sombra | gestores que pasaron a vivo, asignadores en due diligence, comités de riesgo | `live_returns.csv` | integridad del período, vivo contra sombra, deterioro, quiebre estructural (CUSUM), calidad de ejecución, declarado contra realizado |

**Cómo se activan.** Un módulo corre solo cuando en la carpeta de entrada está alguno de sus archivos de detección; una
carpeta que solo tiene insumos del núcleo no produce salida de casos de uso. `--use-case NOMBRE` (repetible, o `all`)
fuerza un módulo: si faltan sus tablas, cada control informa NOT_EXECUTABLE y dice qué insumo falta. El comando
`lockin-validate usecases` lista los módulos con su público, sus tablas y sus controles; los clientes MCP tienen la
misma lista con `list_use_cases`, y `lockin-validate init` escribe una plantilla de cada tabla. Hay un documento por
módulo en `docs/usecases/` y el contrato para escribir un módulo nuevo está en `docs/dev/USECASE_MODULE_GUIDE.md`.

```bash
uv run lockin-validate usecases                                   # lista los módulos
uv run lockin-validate run mis_insumos_riesgo/ --out revision/    # con var_forecasts.csv corre risk solo
uv run lockin-validate run mis_insumos/ --use-case portfolio --out revision/   # forzar un módulo
```

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
