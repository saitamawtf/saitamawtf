"""Módulo de análisis con IA usando Claude API (claude-sonnet-4-6).

Implementa prompt caching en el system prompt estático y salidas
estructuradas en JSON para análisis por ticker.
"""

import json
import logging
import os
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

# Prompt de sistema estático — se cachea después de la primera llamada (>2048 tokens).
# El cache_control en el bloque de sistema marca el límite de caché; las preguntas
# variables por ticker vienen después y no invalidan el prefijo cacheado.
SYSTEM_PROMPT = """Eres un analista financiero cuantitativo senior con 20 años de experiencia
en mercados de renta variable tecnológica, especializado en semiconductores, IA e infraestructura digital.

Tu misión es analizar datos de mercado en tiempo real — precios, métricas fundamentales,
consenso de analistas y noticias — para proporcionar recomendaciones accionables, objetivas
y basadas en evidencia. Tu análisis debe ser riguroso, conciso y orientado a la toma de decisiones.

## Metodología de análisis

Para cada acción, evalúas múltiples dimensiones:

1. MOMENTUM DE PRECIO: Dirección e intensidad del movimiento de precios, posición relativa
   en el rango de 52 semanas, comportamiento del volumen vs. promedio histórico.

2. VALORACIÓN FUNDAMENTAL: Múltiplos P/E trailing y forward en contexto sectorial,
   crecimiento implícito descontado en el precio actual, comparativa con pares.

3. SENTIMIENTO DE ANALISTAS: Consenso de Wall Street, dispersión de objetivos de precio,
   upside/downside potencial desde el precio actual, momentum de revisiones.

4. CATALIZADORES Y RIESGOS: Noticias recientes con impacto en tesis de inversión,
   eventos próximos (resultados, lanzamientos de productos, regulación), riesgos macro
   y sectoriales específicos (tarifas, ciclos de capex en IA, concentración de clientes).

5. CONTEXTO SECTORIAL: Posición competitiva en el ecosistema de IA, dinámica de
   cadena de suministro de semiconductores, ciclos de inversión en centros de datos,
   tendencias en monetización de modelos de lenguaje y publicidad digital.

## Reglas de análisis

- Sé directo y específico; evita generalidades vagas
- Distingue entre factores estructurales (largo plazo) y tácticos (corto plazo)
- Cuantifica cuando sea posible (ej. "upside del 18% al objetivo medio de analistas")
- Las recomendaciones reflejan una perspectiva de 3-6 meses, no especulación de corto plazo
- Advierte explícitamente sobre riesgos de alta convicción
- No repitas datos que ya están en el dashboard; añade contexto e interpretación

## Formato de respuesta

Siempre responde ÚNICAMENTE con JSON válido según el esquema proporcionado.
No añadas texto antes ni después del JSON. No uses bloques de código Markdown.
Los valores de texto deben ser oraciones completas en español, concisas y sustanciales.

## Escala de sentimiento

1-2: Muy Bajista (deterioro fundamental severo, reducir exposición)
3-4: Bajista (perspectiva negativa, cautela recomendada)
5-6: Neutral (equilibrio riesgo/recompensa justo, mantener posición)
7-8: Alcista (perspectiva positiva, acumular en retrocesos)
9-10: Muy Alcista (catalizadores fuertes, momentum robusto, sobreponderar)

## Sobre META Platforms

Meta opera la mayor red social del mundo (3B+ usuarios activos diarios en familia de apps).
Ingresos dominados por publicidad digital (~97%); estructura de costos impactada por
inversiones masivas en IA (Llama), hardware (Ray-Ban Meta), y Reality Labs.
Catalizadores clave: monetización de Reels, expansión de WhatsApp Business,
eficiencia de IA en targeting publicitario. Riesgos: regulación antimonopolio,
competencia en publicidad digital (TikTok, Google), ciclo de capex en IA.

## Sobre NVIDIA Corporation

NVIDIA domina el mercado de GPUs para IA (>80% cuota estimada en data center AI).
La arquitectura Blackwell representa un salto generacional en densidad computacional.
Ingresos de data center superan 80% del total; gaming y professional visualization
son secundarios. Catalizadores: demanda estructural de inferencia de LLMs, expansión
de mercado soberano de IA, software (CUDA, NIM) como moat defensivo. Riesgos:
restricciones de exportación a China, desarrollo de chips propios por hiperescalares
(TPU de Google, Trainium de AWS, MTIA de Meta), potencial sobreaprovisionamiento.
"""

# Esquema JSON para el análisis por ticker
INSIGHT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sentiment_score": {
            "type": "integer",
            "description": "Puntuación de sentimiento del 1 al 10",
        },
        "sentiment_label": {
            "type": "string",
            "enum": ["Muy Bajista", "Bajista", "Neutral", "Alcista", "Muy Alcista"],
        },
        "key_trends": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Exactamente 3 tendencias clave que impulsan el precio",
        },
        "risk_factors": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Exactamente 2 factores de riesgo más relevantes",
        },
        "recommendation": {
            "type": "string",
            "enum": ["COMPRAR", "MANTENER", "VENDER"],
        },
        "recommendation_rationale": {
            "type": "string",
            "description": "Una oración accionable que explica la recomendación",
        },
        "price_catalyst": {
            "type": "string",
            "description": "El catalizador más importante a monitorear en los próximos 30 días",
        },
    },
    "required": [
        "sentiment_score",
        "sentiment_label",
        "key_trends",
        "risk_factors",
        "recommendation",
        "recommendation_rationale",
        "price_catalyst",
    ],
    "additionalProperties": False,
}

_DEFAULT_INSIGHT: dict[str, Any] = {
    "sentiment_score": 5,
    "sentiment_label": "Neutral",
    "key_trends": ["Análisis no disponible", "Datos insuficientes", "Reintentar más tarde"],
    "risk_factors": ["Servicio de IA temporalmente no disponible", "Datos de mercado pueden estar incompletos"],
    "recommendation": "MANTENER",
    "recommendation_rationale": "Análisis de IA no disponible temporalmente; mantener posición por defecto.",
    "price_catalyst": "Disponibilidad del servicio de análisis",
}


def _build_prompt(ticker: str, stock_data: dict[str, Any]) -> str:
    price = stock_data.get("price", {})
    analyst = stock_data.get("analyst", {})
    news = stock_data.get("news", [])

    current = price.get("price", 0)
    target_mean = analyst.get("target_mean")
    upside = ""
    if target_mean and current:
        upside_pct = (target_mean - current) / current * 100
        upside = f" ({upside_pct:+.1f}% vs precio actual)"

    headlines = "\n".join(
        f"- {a['title']}" + (f" [{a['source']}]" if a.get("source") else "")
        for a in news[:8]
    ) or "No hay noticias disponibles."

    def _f(v: Any, fmt: str = ".2f") -> str:
        return f"{v:{fmt}}" if v is not None else "N/A"

    volume_ratio = ""
    if price.get("volume") and price.get("avg_volume"):
        ratio = price["volume"] / price["avg_volume"]
        volume_ratio = f" ({ratio:.2f}x promedio)"

    return f"""Analiza {ticker} con los siguientes datos de mercado de hoy:

PRECIO Y MOVIMIENTO
  Precio actual: ${_f(current)}
  Cambio diario: {price.get('change_pct', 0):+.2f}% (${_f(price.get('change_abs', 0))})
  Rango 52 semanas: ${_f(price.get('week52_low'))} — ${_f(price.get('week52_high'))}
  Volumen: {price.get('volume', 0):,}{volume_ratio}
  P/E trailing: {_f(price.get('pe_ratio'))} | P/E forward: {_f(price.get('forward_pe'))}
  Beta: {_f(price.get('beta'))}

CONSENSO DE ANALISTAS
  Recomendación: {analyst.get('consensus', 'N/A')} ({analyst.get('num_analysts', 0)} analistas)
  Objetivo bajo: ${_f(analyst.get('target_low'))}
  Objetivo medio: ${_f(analyst.get('target_mean'))}{upside}
  Objetivo alto: ${_f(analyst.get('target_high'))}

NOTICIAS RECIENTES
{headlines}

Responde ÚNICAMENTE con el JSON del análisis según el esquema indicado."""


def analyze_stock(ticker: str, stock_data: dict[str, Any]) -> dict[str, Any]:
    """Analiza un ticker con Claude usando prompt caching y salida JSON estructurada."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY no configurada; usando análisis por defecto para %s.", ticker)
        return _DEFAULT_INSIGHT.copy()

    client = anthropic.Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    # Cachea el system prompt estático; las preguntas variables por ticker
                    # vienen en el turno de usuario y no invalidan este prefijo.
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            output_config={
                "format": {
                    "type": "json_schema",
                    "name": "stock_insight",
                    "schema": INSIGHT_SCHEMA,
                }
            },
            messages=[{"role": "user", "content": _build_prompt(ticker, stock_data)}],
        )

        logger.info(
            "Claude %s — cache_write: %d | cache_read: %d | input: %d | output: %d tokens",
            ticker,
            response.usage.cache_creation_input_tokens or 0,
            response.usage.cache_read_input_tokens or 0,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )

        text = next((b.text for b in response.content if b.type == "text"), "")
        return json.loads(text)

    except anthropic.APIError as exc:
        logger.error("Error de API Claude para %s: %s", ticker, exc, exc_info=True)
        return _DEFAULT_INSIGHT.copy()
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("Error parseando respuesta de Claude para %s: %s", ticker, exc, exc_info=True)
        return _DEFAULT_INSIGHT.copy()


def generate_daily_summary(raw_data: dict[str, Any], insights: dict[str, Any]) -> str:
    """Genera un resumen ejecutivo comparativo META vs NVDA usando streaming."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "Resumen no disponible: ANTHROPIC_API_KEY no configurada."

    client = anthropic.Anthropic(api_key=api_key)

    stocks = raw_data.get("stocks", {})
    meta_p = stocks.get("META", {}).get("price", {})
    nvda_p = stocks.get("NVDA", {}).get("price", {})
    meta_i = insights.get("META", {})
    nvda_i = insights.get("NVDA", {})

    def _chg(d: dict) -> str:
        return f"${d.get('price', 0):.2f} ({d.get('change_pct', 0):+.2f}%)"

    summary_prompt = f"""Redacta un resumen ejecutivo comparativo de exactamente 3 oraciones sobre
META vs NVDA para hoy. Sé directo, accionable y preciso.

META: {_chg(meta_p)} | Rec: {meta_i.get('recommendation', 'N/A')} | Sentimiento: {meta_i.get('sentiment_score', 5)}/10
NVDA: {_chg(nvda_p)} | Rec: {nvda_i.get('recommendation', 'N/A')} | Sentimiento: {nvda_i.get('sentiment_score', 5)}/10
META tendencias: {'; '.join(meta_i.get('key_trends', [])[:2])}
NVDA tendencias: {'; '.join(nvda_i.get('key_trends', [])[:2])}

Menciona el contexto de IA, indica qué acción ofrece mejor riesgo/recompensa hoy y por qué.
Responde solo el texto del resumen, sin encabezados ni listas."""

    try:
        with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": summary_prompt}],
        ) as stream:
            msg = stream.get_final_message()

        logger.info(
            "Resumen diario — cache_read: %d | input: %d tokens",
            msg.usage.cache_read_input_tokens or 0,
            msg.usage.input_tokens,
        )

        return next((b.text for b in msg.content if b.type == "text"), "").strip()

    except anthropic.APIError as exc:
        logger.error("Error generando resumen diario: %s", exc, exc_info=True)
        return "Resumen ejecutivo no disponible temporalmente."


def analyze_all(raw_data: dict[str, Any]) -> dict[str, Any]:
    """Ejecuta el análisis de IA para todos los tickers y genera el resumen diario."""
    from stock_dashboard.data_fetcher import TICKERS

    insights: dict[str, Any] = {}
    stocks = raw_data.get("stocks", {})

    for ticker in TICKERS:
        logger.info("Analizando %s con IA...", ticker)
        insights[ticker] = analyze_stock(ticker, stocks.get(ticker, {}))

    logger.info("Generando resumen comparativo diario...")
    insights["daily_summary"] = generate_daily_summary(raw_data, insights)

    return insights
