"""Tests for benchmark_formats: detection, parsing and shape-preserving export
for every supported benchmark file format, plus the entity highlighting."""
import json

import pytest

from benchmark_formats import (
    BatchResult,
    detect_format,
    parse_benchmark,
)

NEW_Q = "What is the capital of Mars?"
NEW_S = "SELECT ?x WHERE { wd:Q111 wdt:P36 ?x }"


def _results(records):
    return [
        BatchResult(record=r, new_question=NEW_Q, new_query=NEW_S) for r in records
    ]


def _roundtrip(filename, content):
    fmt, records = parse_benchmark(filename, content.encode("utf-8"))
    exported = fmt.export(_results(records))
    return fmt, records, exported


# --- QALD family ---------------------------------------------------------------

QALD_JSON = json.dumps({
    "questions": [
        {
            "id": "42",
            "question": [
                {"language": "de", "string": "Was ist die Hauptstadt von Kuba?"},
                {"language": "en", "string": "What is the capital of Cuba?"},
            ],
            "query": {"sparql": "SELECT ?x WHERE { wd:Q241 wdt:P36 ?x }"},
            "answers": [{"head": {}}],
        }
    ]
})


def test_qald_json():
    fmt, records, exported = _roundtrip("qald-9-test.json", QALD_JSON)
    assert fmt.name == "QALD JSON"
    assert len(records) == 1
    assert records[0].question == "What is the capital of Cuba?"
    assert records[0].language == "en"
    assert records[0].query.startswith("SELECT ?x WHERE { wd:Q241")
    doc = json.loads(exported)
    item = doc["questions"][0]
    assert item["id"] == "42"
    assert item["query"]["sparql"] == NEW_S
    # only the transformed language remains; stale answers dropped
    assert [q["string"] for q in item["question"]] == [NEW_Q]
    assert "answers" not in item


def test_dblp_quad_single_question_object():
    content = json.dumps({
        "questions": [
            {
                "id": "Q0001",
                "question": {"string": "What are the papers written by X?"},
                "query": {"sparql": "SELECT ?a WHERE { ?a dblp:authoredBy <p> }"},
            }
        ]
    })
    fmt, records, exported = _roundtrip("DBLP-QuAD.json", content)
    assert records[0].question == "What are the papers written by X?"
    item = json.loads(exported)["questions"][0]
    assert item["question"]["string"] == NEW_Q
    assert item["query"]["sparql"] == NEW_S


def test_bestiary_target_field():
    content = json.dumps({
        "questions": [
            {
                "id": "1",
                "question": [{"language": "en", "string": "which creatures fly"}],
                "target": "SELECT ?v1 WHERE { ?v1 ont:canFly true }",
            }
        ]
    })
    fmt, records, exported = _roundtrip("beastiary_with_qald_format.json", content)
    assert records[0].query.startswith("SELECT ?v1")
    assert json.loads(exported)["questions"][0]["target"] == NEW_S


QALD_XML = """<?xml version="1.0" ?>
<dataset id="qald-4_task_2">
  <question id="7">
    <string lang="en">Which diseases is Cetuximab used for?</string>
    <query>SELECT DISTINCT ?v WHERE { ?x drugbank:possibleDiseaseTarget ?v }</query>
  </question>
</dataset>"""


def test_qald_xml():
    fmt, records, exported = _roundtrip("qald-4_biomedical_train.xml", QALD_XML)
    assert fmt.name == "QALD XML"
    assert records[0].id == "7"
    assert records[0].question == "Which diseases is Cetuximab used for?"
    assert "<string" in exported and NEW_Q in exported and NEW_S in exported


# --- JSON list formats -----------------------------------------------------------

def test_lcquad1():
    content = json.dumps([
        {
            "_id": "1501",
            "corrected_question": "How many movies did Stanley Kubrick direct?",
            "sparql_query": "SELECT DISTINCT COUNT(?uri) WHERE { ?uri dbo:director dbr:Stanley_Kubrick }",
            "sparql_template_id": 101,
        }
    ])
    fmt, records, exported = _roundtrip("lcquad-train-data.json", content)
    assert fmt.name == "LC-QuAD 1.0"
    assert records[0].id == "1501"
    item = json.loads(exported)[0]
    assert item["corrected_question"] == NEW_Q
    assert item["sparql_query"] == NEW_S
    assert item["sparql_template_id"] == 101  # untouched extra field survives


def test_lcquad2():
    content = json.dumps([
        {
            "uid": 19719,
            "question": "What country is Mahmoud Abbas the head of state of?",
            "paraphrased_question": "Mahmoud Abbas is the head of state of what country?",
            "sparql_wikidata": "SELECT DISTINCT ?sbj WHERE { ?sbj wdt:P35 wd:Q127998 }",
            "sparql_dbpedia18": "SELECT DISTINCT ?sbj WHERE { ... }",
        }
    ])
    fmt, records, exported = _roundtrip("lcquad2-test.json", content)
    assert fmt.name == "LC-QuAD 2.0"
    item = json.loads(exported)[0]
    assert item["question"] == NEW_Q
    assert item["sparql_wikidata"] == NEW_S


def test_rubq():
    content = json.dumps([
        {
            "uid": 4,
            "question_text": "Какой стране принадлежит остров Пасхи?",
            "question_eng": "What country does Easter Island belong to?",
            "query": "SELECT ?answer WHERE { wd:Q14452 wdt:P17 ?answer }",
        }
    ])
    fmt, records, exported = _roundtrip("RuBQ_2.0_test.json", content)
    assert fmt.name == "RuBQ"
    assert records[0].language == "ru"
    item = json.loads(exported)[0]
    assert item["question_text"] == NEW_Q
    assert item["query"] == NEW_S


def test_grailqa():
    content = json.dumps([
        {
            "qid": "2100269009000",
            "question": "what is the role of opera designer gig?",
            "sparql_query": "SELECT (?x0 AS ?value) WHERE { ?x0 :type.object.type :opera.opera_designer_role }",
        }
    ])
    fmt, records, exported = _roundtrip("grailqa_v1.0_dev.json", content)
    assert fmt.name == "GrailQA"
    assert json.loads(exported)[0]["sparql_query"] == NEW_S


def test_question_sparql_list_kqapro_cwq():
    content = json.dumps([
        {
            "ID": "WebQTest-12",
            "question": "Which town has a TOID of 4000000074573917?",
            "sparql": "SELECT DISTINCT ?e WHERE { ?e <TOID> ?pv }",
        }
    ])
    fmt, records, exported = _roundtrip("ComplexWebQuestions_test.json", content)
    assert fmt.name == "JSON list (question + sparql)"
    assert records[0].id == "WebQTest-12"
    item = json.loads(exported)[0]
    assert item["question"] == NEW_Q and item["sparql"] == NEW_S


def test_dynbench_flat():
    content = json.dumps([
        {
            "id": "train:1",
            "language": "en",
            "old pagerank": 130,
            "new pagerank": 106,
            "question": "List all boardgames by GMT.",
            "new question": "List all card games by GMT.",
            "query": "SELECT ?uri WHERE { ?uri wdt:P31 wd:Q131436 . }",
            "new query": "SELECT ?uri WHERE { ?uri wdt:P31 wd:Q142714 . }",
        }
    ])
    fmt, records, exported = _roundtrip("DynQALD.json", content)
    assert fmt.name == "DynBench JSON"
    assert records[0].language == "en"
    item = json.loads(exported)[0]
    assert item["question"] == NEW_Q and item["query"] == NEW_S
    assert "new question" not in item  # stale precomputed pair removed


def test_webqsp():
    content = json.dumps({
        "Questions": [
            {
                "QuestionId": "WebQTest-0",
                "RawQuestion": "what does jamaican people speak?",
                "Parses": [
                    {"Sparql": "SELECT DISTINCT ?x WHERE { ns:m.03_r3 ns:location.country.languages_spoken ?x }"},
                    {"Sparql": "SELECT ..."},
                ],
            }
        ]
    })
    fmt, records, exported = _roundtrip("WebQSP.test.json", content)
    assert fmt.name == "WebQuestionsSP"
    item = json.loads(exported)["Questions"][0]
    assert item["RawQuestion"] == NEW_Q
    assert item["Parses"][0]["Sparql"] == NEW_S
    assert len(item["Parses"]) == 1


# --- text formats -----------------------------------------------------------------

def test_csv():
    content = "question,query\nHow many singers do we have?,SELECT (count(*) AS ?n) WHERE { ?t1 a :singer }\n"
    fmt, records, exported = _roundtrip("dev_nl_sparql.csv", content)
    assert fmt.name == "CSV / TSV"
    assert records[0].question == "How many singers do we have?"
    lines = exported.strip().split("\n")
    assert lines[0] == "question,query"
    assert NEW_Q in lines[1] and "wd:Q111" in lines[1]


def test_tsv():
    content = "question\tsparql\nDid M3 edit M0?\tASK WHERE { M3 wdt:P57 ?x0 }\n"
    fmt, records, exported = _roundtrip("mcd1_dev.tsv", content)
    assert fmt.name == "CSV / TSV"
    assert records[0].query == "ASK WHERE { M3 wdt:P57 ?x0 }"
    assert exported.startswith("question\tsparql\n")
    assert f"{NEW_Q}\t" in exported


def test_sparql_comment_file():
    content = (
        "#the scientific name of species in bgee and their taxon\n"
        "PREFIX up:<http://purl.uniprot.org/core/>\n"
        "SELECT * { ?taxon a up:Taxon . ?taxon up:scientificName ?name }\n"
    )
    fmt, records, exported = _roundtrip("Q1.rq", content)
    assert fmt.name == "SPARQL file (.rq/.sparql)"
    assert records[0].question.startswith("the scientific name")
    assert records[0].query.startswith("PREFIX up:")
    assert exported.startswith(f"#{NEW_Q}\n{NEW_S}")


def test_sib_turtle():
    content = (
        "@prefix sh: <http://www.w3.org/ns/shacl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "[] a sh:SPARQLExecutable ;\n"
        '  rdfs:comment "List the proteins encoded by a gene in an organelle" ;\n'
        '  sh:select """SELECT ?protein WHERE { ?protein a up:Protein }""" .\n'
    )
    fmt, records, exported = _roundtrip("001.ttl", content)
    assert fmt.name == "SIB sparql-examples (Turtle)"
    assert records[0].question.startswith("List the proteins")
    assert NEW_Q in exported and NEW_S in exported


# --- error handling ----------------------------------------------------------------

def test_unknown_format_raises():
    with pytest.raises(ValueError, match="Unsupported"):
        parse_benchmark("notes.txt", b"just some plain text without structure")


def test_recognized_but_empty_raises():
    with pytest.raises(ValueError, match="no usable"):
        parse_benchmark("empty-qald.json", json.dumps({"questions": [{"id": "1"}]}).encode())


def test_detect_binary_garbage():
    fmt, text = detect_format("data.json", b"\xff\xfe\x00\x01")
    assert fmt is None


def test_limit_is_callers_concern_full_parse():
    many = json.dumps([
        {"id": str(i), "question": f"q{i}?", "query": f"SELECT {i}"}
        for i in range(100)
    ])
    _, records = parse_benchmark("big.json", many.encode())
    assert len(records) == 100


# --- entity highlighting (batch_ui) --------------------------------------------------

def test_highlight_entity():
    from batch_ui import highlight_entity

    out = highlight_entity(
        "List all boardgames by GMT.", "GMT", "wd:Q1136320"
    )
    assert '<span class="entity-mark">GMT' in out
    assert "https://www.wikidata.org/wiki/Q1136320" in out
    assert "entity-overlay" in out


def test_highlight_entity_escapes_html():
    from batch_ui import highlight_entity

    out = highlight_entity("Is <b>bold</b> by AT&T?", "AT&T", "wd:Q35476")
    assert "<b>" not in out  # question HTML is escaped
    assert "AT&amp;T" in out


def test_highlight_entity_label_not_found():
    from batch_ui import highlight_entity

    out = highlight_entity("A question without the entity.", "Missing Label", "wd:Q1")
    assert "entity-mark" not in out
    assert out == "A question without the entity."
