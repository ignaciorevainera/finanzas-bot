# Submenús Para Campos Faltantes: Diseño

**Fecha:** 2026-08-12

## Objetivo

Usar teclados inline de Telegram para responder campos con opciones cerradas cuando Gemini no los detecta, manteniendo texto libre para datos abiertos y sin alterar campos ya extraídos.

## Alcance

Submenús aparecen solo cuando campo correspondiente falta.

- `type`: `Gasto` / `Ingreso`.
- `category`: 16 categorías base + `Otra categoría`, en un teclado único de dos columnas.
- `payment_method`: `Efectivo`, `Tarjeta de Débito`, `Tarjeta de Crédito`, `Transferencia`, `Otro`.

Texto libre permanece para `amount`, `description`, distribución compartida, notas, comercio, ubicación y categoría personalizada.

Defaults no abren submenús:

- `currency` ausente: `ARS`.
- `status` ausente: `Completado`.
- `transaction_date` ausente: fecha y hora actuales.

Datos detectados explícitamente saltan preguntas y submenús.

## Reglas De Fecha

Confirmación muestra fecha sin hora cuando usuario no declaró hora. Cuando usuario declaró hora, muestra fecha y hora.

- Sin hora: `12/08/2026`.
- Con hora: `12/08/2026 18:30`.

Fecha actual default no abre teclado. Selector de fecha aparece solo en flujo explícito de cambio o cuando estado legado entregue fecha faltante.

## Arquitectura

`app/handlers.py` conserva `pending_transactions` y estados existentes. Estado `pick_missing` añade campo actual sin crear wizard paralelo:

```python
{
    "action": "pick_missing",
    "field": "category",
    "missing_fields": ["category", "payment_method"],
    "missing_index": 0,
    "data": {...},
}
```

Callback y texto equivalente llaman mismo resolver. Resolver normaliza, valida, actualiza `data`, avanza índice y edita mensaje actual. Sin faltantes, vuelve a confirmación.

`app/transaction_schema.py` sigue siendo fuente de vocabularios canónicos. No se duplican mapas de categorías, tipos o métodos en handlers salvo etiquetas visuales y códigos callback.

## Callbacks

Callbacks usan códigos ASCII cortos y únicos:

- `missing_type_expense`
- `missing_type_income`
- `missing_category_<code>` para categorías base.
- `missing_category_other`
- `missing_payment_cash`
- `missing_payment_debit`
- `missing_payment_credit`
- `missing_payment_transfer`
- `missing_payment_other`

Texto visible permanece español completo. Callback desconocido, callback de campo incorrecto o estado ausente no muta datos.

## Flujo

1. `handle_parsed_data` normaliza datos y calcula faltantes.
2. Campo faltante con opciones muestra teclado inline.
3. Campo faltante abierto muestra pregunta textual.
4. Usuario toca botón o escribe respuesta equivalente.
5. Resolver guarda valor canónico español.
6. Bot edita mensaje actual con siguiente pregunta o teclado.
7. `Otra categoría` cambia temporalmente a entrada textual y normaliza categoría personalizada.
8. Sin faltantes, bot muestra confirmación existente.
9. `Aceptar`, `Agregar más` y `Cancelar` mantienen estados actuales.

Texto equivalente funciona como fallback:

- `gasto` equivale a `Gasto`.
- `comida` equivale a `Comida`.
- `efectivo` equivale a `Efectivo`.

Texto inválido conserva estado y repite pregunta. Selección válida no envía mensajes duplicados: edita mensaje de pregunta.

## Compatibilidad Con Estados

No cambiar comportamiento de:

- `pick_split` y validación de distribución exacta.
- `pick_date` y `wait_custom_date`.
- `add_context` iterativo.
- Confirmación `Aceptar` / `Agregar más` / `Cancelar`.
- Eliminación de transacciones.
- Reportes y preguntas naturales.

Callback handler valida chat, estado, acción y campo antes de aplicar respuesta. Callback viejo no puede modificar otra transacción pendiente.

## Pruebas

- Campo detectado no abre teclado.
- Faltante `type` muestra dos opciones y guarda valor correcto.
- Faltante `category` muestra 16 categorías + `Otra categoría` en dos columnas.
- Faltante `payment_method` muestra cinco opciones y guarda valor correcto.
- Selección válida avanza al siguiente faltante y edita mensaje.
- Texto equivalente funciona como fallback.
- Texto inválido repite pregunta sin mutar datos.
- `Otra categoría` acepta texto y normaliza primera letra.
- Callback desconocido, estado ausente o campo incorrecto no muta datos.
- Orden de faltantes: `type`, `amount`, `category`, `description`, `payment_method`.
- Confirmación muestra fecha sin hora o con hora según entrada.
- Regresión de `pick_split`, `add_context`, `Aceptar`, `Cancelar`, texto y audio.

## Criterios De Aceptación

- Ningún campo ya detectado genera pregunta redundante.
- Opciones cerradas ofrecen botones inline cuando faltan.
- Respuestas textuales equivalentes siguen funcionando.
- Categorías personalizadas siguen permitidas mediante `Otra categoría`.
- Cada selección avanza dentro del mismo mensaje, sin duplicados.
- Valores persistidos mantienen vocabulario español capitalizado.
- Estados pendientes existentes no sufren regresiones.
