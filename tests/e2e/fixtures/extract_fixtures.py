"""Extract the benchmark-file subsets used by the end-to-end upload tests.

Each fixture is a small subset (first N records) cut from the ORIGINAL
benchmark file, preserving the exact file structure of the original, so the
e2e tests exercise the real formats. Sources and licenses: see README.md in
this directory.

Run manually to (re)create the fixtures:

    python tests/e2e/fixtures/extract_fixtures.py
"""
import io
import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import requests

HERE = Path(__file__).parent
REPO_ROOT = HERE.parents[2]
N = 2  # records per fixture


def fetch(url: str, timeout: int = 120) -> bytes:
    print(f"  fetching {url}")
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.content


def write(name: str, data) -> None:
    path = HERE / name
    if isinstance(data, (dict, list)):
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    elif isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    print(f"  wrote {path.name} ({path.stat().st_size} bytes)")


def qald_9() -> None:
    doc = json.loads(fetch(
        "https://raw.githubusercontent.com/ag-sc/QALD/master/9/data/qald-9-test-multilingual.json"
    ))
    doc["questions"] = doc["questions"][:N]
    write("qald-9-test.subset.json", doc)


def qald_4_biomedical_xml() -> None:
    root = ET.fromstring(fetch(
        "https://raw.githubusercontent.com/ag-sc/QALD/master/4/data/qald-4_biomedical_train.xml"
    ).decode("utf-8"))
    for q in list(root.findall("question"))[N:]:
        root.remove(q)
    ET.indent(root)
    write(
        "qald-4-biomedical-train.subset.xml",
        ET.tostring(root, encoding="unicode", xml_declaration=True),
    )


def lcquad_1() -> None:
    data = json.loads(fetch(
        "https://raw.githubusercontent.com/AskNowQA/LC-QuAD/data/train-data.json"
    ))
    write("lcquad1-train.subset.json", data[:N])


def lcquad_2() -> None:
    data = json.loads(fetch(
        "https://raw.githubusercontent.com/AskNowQA/LC-QuAD2.0/master/dataset/test.json"
    ))
    write("lcquad2-test.subset.json", data[:N])


def rubq_2() -> None:
    data = json.loads(fetch(
        "https://raw.githubusercontent.com/vladislavneon/RuBQ/master/RuBQ_2.0/RuBQ_2.0_test.json"
    ))
    write("rubq-2.0-test.subset.json", data[:N])


def grailqa() -> None:
    # official GrailQA download is behind a JS gate; the HF mirror preserves
    # the original record structure (qid, question, sparql_query, …)
    doc = json.loads(fetch(
        "https://datasets-server.huggingface.co/first-rows"
        "?dataset=Hieuman%2Fgrail_qa&config=default&split=validation"
    ))
    rows = [r["row"] for r in doc["rows"][:N]]
    write("grailqa-validation.subset.json", rows)


def complexwebquestions() -> None:
    doc = json.loads(fetch(
        "https://datasets-server.huggingface.co/first-rows"
        "?dataset=drt%2Fcomplex_web_questions&config=complex_web_questions&split=validation"
    ))
    rows = [r["row"] for r in doc["rows"][:N]]
    write("complexwebquestions-validation.subset.json", rows)


def webqsp() -> None:
    blob = fetch(
        "https://download.microsoft.com/download/f/5/0/"
        "f5012144-a4fb-4084-897f-cfda99c60bdf/WebQSP.zip"
    )
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        inner = next(n for n in zf.namelist() if n.endswith("WebQSP.test.json"))
        doc = json.loads(zf.read(inner))
    doc["Questions"] = doc["Questions"][:N]
    write("webqsp-test.subset.json", doc)


def bestiary() -> None:
    blob = fetch("https://github.com/danrd/sparqlgen/raw/main/beastiary_with_qald_format.json.zip")
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        inner = next(n for n in zf.namelist() if n.endswith(".json"))
        doc = json.loads(zf.read(inner))
    doc["questions"] = doc["questions"][:N]
    write("beastiary-qald-format.subset.json", doc)


def dynqald() -> None:
    data = json.loads((REPO_ROOT / "benchmarks" / "DynQALD.json").read_text(encoding="utf-8"))
    write("dynqald.subset.json", data[:N])


def spider4sparql_csv() -> None:
    text = fetch(
        "https://raw.githubusercontent.com/ckosten/spider4sparql/main/"
        "nl_sparql_pairs/dev/dev_nl_sparql.csv"
    ).decode("utf-8")
    lines = text.splitlines()
    write("spider4sparql-dev.subset.csv", "\n".join(lines[: N + 1]) + "\n")  # header + N rows


def bio_soda_rq() -> None:
    write("bio-soda-bgee-q1.rq", fetch(
        "https://raw.githubusercontent.com/anazhaw/Bio-SODA/master/"
        "Benchmarks/Bioinformatics/Bgee/Q1.rq"
    ))


def sib_ttl() -> None:
    write("sib-uniprot-100.ttl", fetch(
        "https://raw.githubusercontent.com/sib-swiss/sparql-examples/master/"
        "examples/UniProt/100_uniprot_organelles_or_plasmids.ttl"
    ))


if __name__ == "__main__":
    for extractor in (
        qald_9, qald_4_biomedical_xml, lcquad_1, lcquad_2, rubq_2, grailqa,
        complexwebquestions, webqsp, bestiary, dynqald, spider4sparql_csv,
        bio_soda_rq, sib_ttl,
    ):
        print(extractor.__name__)
        extractor()
    print("done")
