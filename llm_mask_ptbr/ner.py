from .detectors import Span


def presidio(model="pt_core_news_lg", entities=None, threshold=0.5):
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider

    entities = entities or {"PERSON": "PESSOA"}
    engine = NlpEngineProvider(nlp_configuration={
        "nlp_engine_name": "spacy", "models": [{"lang_code": "pt", "model_name": model}]}).create_engine()
    analyzer = AnalyzerEngine(nlp_engine=engine, supported_languages=["pt"])

    def detect(text):
        results = analyzer.analyze(text=text, language="pt", entities=list(entities), score_threshold=threshold)
        return [Span(result.start, result.end, entities[result.entity_type]) for result in results]

    return detect
