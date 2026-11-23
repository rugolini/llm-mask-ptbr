FROM python:3.12-slim

# NER=1 adds Presidio and the Portuguese spaCy model (about 1 GB more).
ARG NER=0
ARG NER_MODEL=pt_core_news_lg

WORKDIR /app
COPY pyproject.toml README.md ./
COPY llm_mask_ptbr ./llm_mask_ptbr
RUN pip install --no-cache-dir . \
    && if [ "$NER" = "1" ]; then pip install --no-cache-dir ".[ner]" && python -m spacy download "$NER_MODEL"; fi \
    && useradd --uid 10001 --create-home mask && mkdir /data && chown mask /data

USER mask
ENV LLM_MASK_VAULT=/data/vault.db
EXPOSE 8400
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8400/_mask/health')"
CMD ["llm-mask-ptbr"]
