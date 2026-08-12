# Registro Financiero Contextual y Reportes: Diseño

**Fecha:** 2026-08-11

## Objetivo

Permitir que bot registre gastos e ingresos desde texto o audio, usando cada campo de DB según su significado, preguntando datos obligatorios faltantes y conservando contexto financiero adicional para reportes personales precisos.

Trabajo se divide en dos planes secuenciales:

1. Registro inteligente y modelo de datos.
2. Reportes y consultas en lenguaje natural.

## Contexto Actual

Aplicación Python usa Telegram, Gemini, FastAPI y PostgreSQL en Neon mediante `asyncpg`.

- `app/gemini_ai.py` extrae transacciones desde texto y audio.
- `app/handlers.py` gestiona preguntas de método de pago, fecha y confirmación.
- `app/database.py` crea tabla `transactions` e inserta registros.
- `description` existe, pero prompt actual lo usa como concepto sin separar claramente contexto adicional.
- Categorías y métodos actuales se almacenan en inglés.
- `payment_method` es obligatorio en DB, aunque parser puede devolver `null`.
- Confirmación actual solo ofrece aceptar o cancelar.

## Decisiones De Producto

### Campos básicos

- `type`: `Gasto` o `Ingreso`; obligatorio.
- `amount`: parte personal del movimiento; obligatorio.
- `total_amount`: monto completo; igual a `amount` cuando no hay reparto.
- `currency`: código ISO de moneda; default `ARS` y no se traduce.
- `category`: categoría en español, capitalizada; obligatoria.
- `description`: título breve del concepto; obligatorio y puede repetirse.
- `merchant`: comercio, empresa, persona pagadora o receptora; solo si aparece explícitamente.
- `payment_method`: `Efectivo`, `Tarjeta de Débito`, `Tarjeta de Crédito`, `Transferencia` u `Otro`; obligatorio.
- `status`: `Completado`, `Pendiente` o `Cancelado`; default `Completado`.
- `location`: lugar físico o plataforma; no duplicar `merchant`.
- `transaction_date`: fecha y hora del movimiento; default fecha y hora actuales.
- `notes`: contexto libre no representable en otro campo.
- `tags`: etiquetas explícitas más etiquetas útiles generadas por IA, sin duplicados.

### Categorías base

`Comida`, `Transporte`, `Entretenimiento`, `Salud`, `Educación`, `Ropa`, `Vivienda`, `Servicios`, `Suscripciones`, `Sueldo`, `Trabajo Independiente`, `Regalo`, `Ahorros`, `Inversión`, `Viajes`, `Otros`.

IA puede crear categorías nuevas cuando ninguna categoría base representa contexto. Todos valores textuales almacenados deben estar en español y capitalizados.

### Métodos de pago base

`Efectivo`, `Tarjeta de Débito`, `Tarjeta de Crédito`, `Transferencia`, `Otro`.

### Datos avanzados

Datos claros y consultables se guardan en columnas directas. Estructuras variables usan JSONB o arrays:

- Cuotas: `installment_number`, `installment_total`.
- Recurrencia: `recurrence`.
- Vencimiento: `due_date`.
- Transferencias: `transfer_details` JSONB.
- Reembolsos: `related_transaction_id`.
- Paquetes: `package_details` JSONB.
- Personas involucradas: `participants` TEXT[].
- Distribución: `split_details` JSONB.

No se crean tablas relacionadas en primera versión. `transactions` sigue siendo tabla principal para reducir joins y mantenimiento.

### Movimientos compartidos

Aplica a gastos e ingresos.

- Movimiento normal: `amount = total_amount`.
- Movimiento compartido: `amount` representa parte personal; `total_amount` representa monto completo.
- Estadísticas personales usan `amount`.
- Reportes compartidos muestran ambos montos.
- Si se mencionan participantes sin distribución exacta, bot pregunta distribución; nunca divide automáticamente.
- Ejemplo: `De 120000, yo puse 30000` guarda `amount=30000`, `total_amount=120000`.
- Ejemplo: `Gasté 50000 con Viole` requiere distribución exacta antes de confirmar.

### Faltantes y ambigüedad

Bot pregunta, uno por uno, por cada dato obligatorio faltante: `type`, `amount`, `category`, `description`, `payment_method`.

Defaults automáticos cubren `currency`, `transaction_date` y `status` cuando no se expresan.

IA no infiere datos ambiguos. Si contexto nuevo es explícito, reemplaza dato anterior; si es ambiguo, conserva dato anterior. Bot vuelve a mostrar confirmación después de enriquecer transacción.

## Flujo De Registro

1. Usuario envía texto o audio.
2. Gemini devuelve mismo contrato estructurado para ambas entradas.
3. Normalizador convierte campos textuales al vocabulario español capitalizado.
4. Sistema aplica defaults.
5. Validador identifica faltantes y reglas de reparto.
6. Bot pregunta faltantes uno por uno.
7. Bot muestra todos campos detectados y datos avanzados.
8. Usuario elige `Aceptar`, `Cancelar` o `Agregar más`.
9. `Aceptar` persiste en Neon.
10. `Cancelar` descarta.
11. `Agregar más` toma siguiente mensaje solo como contexto de transacción pendiente; después vuelve a confirmación.

Confirmación muestra tipo, monto personal, monto total, moneda, categoría, descripción, comercio, método, fecha, estado, participantes, distribución, cuotas, recurrencia, vencimiento, ubicación, etiquetas y notas cuando tengan valor.

## Reportes

Segundo plan consumirá contrato de transacción estabilizado.

- `/summary` se amplía con ingreso, gasto personal, gasto total compartido y flujo neto.
- Nuevos reportes cubren período, categoría, comercio, método de pago, ubicación, persona, etiqueta, cuotas, recurrencias, vencimientos, transferencias, reembolsos, paquetes y movimientos compartidos.
- Comandos fijos y lenguaje natural usan mismo servicio interno.
- Gemini interpreta lenguaje natural y devuelve intención estructurada; nunca genera SQL.
- Consultas SQL parametrizadas viven en capa DB.
- Reportes personales usan `amount`; reportes compartidos comparan `amount` y `total_amount`.

## Pruebas Requeridas

### Registro

- Contrato prompt para texto y audio.
- Normalización de categorías, métodos, estados, etiquetas y capitalización.
- Validación de campos obligatorios.
- Aplicación de defaults.
- Distribución exacta y montos compartidos.
- Cuotas, recurrencia, vencimiento, paquetes, transferencias y reembolsos.
- Flujo `Agregar más`, reemplazo explícito y conservación ante ambigüedad.
- Botones `Aceptar`, `Cancelar` y `Agregar más`.
- Inserción DB con campos directos, arrays y JSONB.
- Regresión para fecha, exportación y resumen existente.

### Reportes

- Consultas por cada dimensión soportada.
- Separación `amount` y `total_amount`.
- Rangos de fecha y filtros parametrizados.
- Interpretación de lenguaje natural en intención conocida.
- Rechazo seguro de intención no soportada.
- Equivalencia funcional entre comando y lenguaje natural.

## Criterios De Aceptación

- Ningún movimiento válido se guarda sin `type`, `amount`, `category`, `description` y `payment_method`.
- Valores textuales persistidos usan español capitalizado; códigos ISO como `ARS` conservan formato ISO.
- Texto y audio producen contrato equivalente.
- `description` contiene solo concepto/título; contexto adicional usa campos específicos, `tags` o `notes`.
- Gastos e ingresos compartidos preservan total y parte personal.
- Estadísticas personales no cuentan partes de terceros.
- Usuario puede enriquecer movimiento una vez antes de aceptar.
- Reportes no dependen de SQL generado por IA.
- Cada plan puede probarse y desplegarse de forma independiente.
