"""
benchmark_formats.py — parse and export KGQA benchmark files in all known formats.

Every format provides:
  * detection (``matches``) on the uploaded file name + content,
  * parsing into a normalized list of :class:`BenchmarkRecord`,
  * a shape-preserving export: the original document structure is deep-copied
    and only the question/query fields are replaced by the computed pair, so
    the exported file has the exact same format as the uploaded one.

Supported formats (see FORMATS at the bottom for the UI descriptions):
  QALD-style JSON (QALD-4…10, QALD-9-plus, DBLP-QuAD, SciQA, VQuAnDa, BESTIARY),
  QALD XML (older QALD editions), LC-QuAD 1.0, LC-QuAD 2.0, RuBQ 1.0/2.0,
  GrailQA, WebQuestionsSP, DynBench flat JSON (DynQALD/DynRuBQ), generic JSON
  lists with question+SPARQL keys (KQA Pro, ComplexWebQuestions, CFQ, …),
  CSV/TSV (e.g. Spider4SPARQL), single SPARQL files with the question as
  comment (Bio-SODA style), and SIB sparql-examples Turtle files.
"""
from __future__ import annotations

import copy
import csv
import io
import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkRecord:
    """One normalized question-query pair from an uploaded benchmark file."""

    id: str
    question: str
    query: str
    language: str = "en"
    raw: Any = field(default=None, repr=False)  # the original item (for export)


@dataclass
class BatchResult:
    """The computed pair for one record (None fields = not processed/failed)."""

    record: BenchmarkRecord
    new_question: Optional[str] = None
    new_query: Optional[str] = None
    response: Any = field(default=None, repr=False)
    error: Optional[str] = None


class BenchmarkFormat:
    """Base class: subclasses implement matches/parse/export."""

    name: str = ""
    description: str = ""
    example: str = ""

    def matches(self, filename: str, text: str, data: Any) -> bool:
        raise NotImplementedError

    def parse(self, text: str, data: Any) -> list[BenchmarkRecord]:
        raise NotImplementedError

    def export(self, results: list[BatchResult]) -> str:
        raise NotImplementedError


# --- helpers -----------------------------------------------------------------

def _first_str(item: dict, keys: tuple[str, ...]) -> Optional[str]:
    for k in keys:
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return None


def _json_dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


# --- QALD family (JSON) ------------------------------------------------------

class QaldJsonFormat(BenchmarkFormat):
    """QALD-style JSON: {"questions": [...]} with multilingual question lists.

    Also covers the single-string variants used by DBLP-QuAD and SciQA
    (question is one dict, not a list) and the BESTIARY export whose SPARQL
    lives in a "target" field instead of query.sparql.
    """

    name = "QALD JSON"
    description = (
        "`{\"questions\": [...]}` as used by QALD-9/9-plus/10, DBLP-QuAD, "
        "SciQA, VQuAnDa and BESTIARY — question as multilingual list, single "
        "object or plain string; SPARQL in `query.sparql`, `query` or `target`"
    )
    example = (
        '{"questions": [{"id": "1", "question": [{"language": "en", '
        '"string": "What is …?"}], "query": {"sparql": "SELECT …"}}]}'
    )

    def matches(self, filename, text, data):
        return isinstance(data, dict) and isinstance(data.get("questions"), list)

    @staticmethod
    def _question_of(item: dict, preferred_language: str = "en"):
        """Return (question, language) from the many QALD question shapes."""
        q = item.get("question")
        if isinstance(q, list):  # multilingual list of {language, string}
            best = None
            for entry in q:
                if not isinstance(entry, dict):
                    continue
                s = entry.get("string") or entry.get("question")
                if not s:
                    continue
                lang = entry.get("language", "en")
                if lang == preferred_language:
                    return s, lang
                if best is None:
                    best = (s, lang)
            return best or (None, None)
        if isinstance(q, dict):
            return q.get("string"), q.get("language", "en")
        if isinstance(q, str):
            return q, item.get("language", "en")
        return None, None

    @staticmethod
    def _query_of(item: dict) -> Optional[str]:
        query = item.get("query")
        if isinstance(query, dict) and isinstance(query.get("sparql"), str):
            return query["sparql"]
        if isinstance(query, str) and query.strip():
            return query
        target = item.get("target")  # BESTIARY
        if isinstance(target, str) and target.strip():
            return target
        return None

    def parse(self, text, data):
        records = []
        for i, item in enumerate(data["questions"]):
            if not isinstance(item, dict):
                continue
            question, lang = self._question_of(item)
            query = self._query_of(item)
            if not question or not query:
                continue
            records.append(
                BenchmarkRecord(
                    id=str(item.get("id", i)),
                    question=question,
                    query=query,
                    language=lang or "en",
                    raw=item,
                )
            )
        return records

    @staticmethod
    def _set_pair(item: dict, result: BatchResult) -> None:
        q = item.get("question")
        lang = result.record.language
        if isinstance(q, list):
            replaced = False
            for entry in q:
                if isinstance(entry, dict) and entry.get("language", "en") == lang:
                    entry["string"] = result.new_question
                    replaced = True
            if not replaced and q and isinstance(q[0], dict):
                q[0]["string"] = result.new_question
            # other languages of the original question no longer match the
            # transformed pair — keep only the transformed language
            item["question"] = [
                e
                for e in q
                if not isinstance(e, dict)
                or e.get("language", "en") == lang
                or not replaced
            ]
        elif isinstance(q, dict):
            q["string"] = result.new_question
        else:
            item["question"] = result.new_question

        query = item.get("query")
        if isinstance(query, dict) and "sparql" in query:
            query["sparql"] = result.new_query
        elif isinstance(query, str):
            item["query"] = result.new_query
        elif isinstance(item.get("target"), str):
            item["target"] = result.new_query
        else:
            item["query"] = {"sparql": result.new_query}
        # answers of the original query do not apply to the new query
        item.pop("answers", None)

    def export(self, results):
        questions = []
        for r in results:
            if r.new_question is None:
                continue
            item = copy.deepcopy(r.record.raw)
            self._set_pair(item, r)
            questions.append(item)
        return _json_dump({"questions": questions})


# --- QALD XML -----------------------------------------------------------------

class QaldXmlFormat(BenchmarkFormat):
    name = "QALD XML"
    description = (
        "XML of older QALD editions (e.g. QALD-4 biomedical): "
        "`<question id=…><string>…</string><query>…</query></question>`"
    )
    example = (
        '<dataset id="qald-4_biomedical"><question id="1">\n'
        "  <string>Which diseases …?</string>\n  <query>SELECT …</query>\n"
        "</question></dataset>"
    )

    def matches(self, filename, text, data):
        if data is not None or "<question" not in text:
            return False
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return False
        return root.find(".//question") is not None

    def parse(self, text, data):
        root = ET.fromstring(text)
        records = []
        for i, q in enumerate(root.iter("question")):
            strings = q.findall("string")
            question, lang = None, "en"
            for s in strings:
                s_lang = s.get("lang", "en")
                if s.text and (question is None or s_lang == "en"):
                    question, lang = s.text.strip(), s_lang
            query_el = q.find("query")
            query = query_el.text.strip() if query_el is not None and query_el.text else None
            if not question or not query:
                continue
            records.append(
                BenchmarkRecord(
                    id=str(q.get("id", i)), question=question, query=query,
                    language=lang, raw=q,
                )
            )
        return records

    def export(self, results):
        root = ET.Element("dataset")
        for r in results:
            if r.new_question is None:
                continue
            q = ET.SubElement(root, "question", id=str(r.record.id))
            s = ET.SubElement(q, "string", lang=r.record.language)
            s.text = r.new_question
            query = ET.SubElement(q, "query")
            query.text = r.new_query
        ET.indent(root)
        return ET.tostring(root, encoding="unicode", xml_declaration=True)


# --- WebQuestionsSP -----------------------------------------------------------

class WebQspFormat(BenchmarkFormat):
    name = "WebQuestionsSP"
    description = (
        "`{\"Questions\": [...]}` with `RawQuestion` and the Freebase SPARQL "
        "in `Parses[0].Sparql`"
    )
    example = (
        '{"Questions": [{"QuestionId": "WebQTest-0", "RawQuestion": '
        '"what does …?", "Parses": [{"Sparql": "SELECT …"}]}]}'
    )

    def matches(self, filename, text, data):
        return isinstance(data, dict) and isinstance(data.get("Questions"), list)

    def parse(self, text, data):
        records = []
        for i, item in enumerate(data["Questions"]):
            question = _first_str(item, ("RawQuestion", "ProcessedQuestion"))
            parses = item.get("Parses") or []
            query = parses[0].get("Sparql") if parses and isinstance(parses[0], dict) else None
            if not question or not query:
                continue
            records.append(
                BenchmarkRecord(
                    id=str(item.get("QuestionId", i)), question=question,
                    query=query, raw=item,
                )
            )
        return records

    def export(self, results):
        questions = []
        for r in results:
            if r.new_question is None:
                continue
            item = copy.deepcopy(r.record.raw)
            item["RawQuestion"] = r.new_question
            if "ProcessedQuestion" in item:
                item["ProcessedQuestion"] = r.new_question
            if item.get("Parses"):
                item["Parses"] = [item["Parses"][0]]
                item["Parses"][0]["Sparql"] = r.new_query
            else:
                item["Parses"] = [{"Sparql": r.new_query}]
            questions.append(item)
        return _json_dump({"Questions": questions})


# --- JSON list formats ---------------------------------------------------------

class _JsonListFormat(BenchmarkFormat):
    """Base for benchmarks that are a JSON list of flat objects."""

    question_keys: tuple[str, ...] = ()
    query_keys: tuple[str, ...] = ()
    id_keys: tuple[str, ...] = ("id", "uid", "_id", "qid", "ID")

    def matches(self, filename, text, data):
        if not (isinstance(data, list) and data and isinstance(data[0], dict)):
            return False
        item = data[0]
        return (
            _first_str(item, self.question_keys) is not None
            and _first_str(item, self.query_keys) is not None
        )

    def parse(self, text, data):
        records = []
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                continue
            question = _first_str(item, self.question_keys)
            query = _first_str(item, self.query_keys)
            if not question or not query:
                continue
            rec_id = next(
                (str(item[k]) for k in self.id_keys if item.get(k) is not None),
                str(i),
            )
            records.append(
                BenchmarkRecord(
                    id=rec_id, question=question, query=query,
                    language=item.get("language", "en"), raw=item,
                )
            )
        return records

    def export(self, results):
        out = []
        for r in results:
            if r.new_question is None:
                continue
            item = copy.deepcopy(r.record.raw)
            # replace exactly the keys the pair was read from
            for k in self.question_keys:
                if isinstance(item.get(k), str):
                    item[k] = r.new_question
                    break
            for k in self.query_keys:
                if isinstance(item.get(k), str):
                    item[k] = r.new_query
                    break
            out.append(item)
        return _json_dump(out)


class LcQuad2Format(_JsonListFormat):
    name = "LC-QuAD 2.0"
    description = (
        "JSON list with `question`/`paraphrased_question` and "
        "`sparql_wikidata` (DBpedia variant in `sparql_dbpedia`)"
    )
    example = (
        '[{"uid": 1, "question": "What is …?", "paraphrased_question": "…", '
        '"sparql_wikidata": "SELECT …"}]'
    )
    question_keys = ("question", "paraphrased_question", "NNQT_question")
    query_keys = ("sparql_wikidata", "sparql_dbpedia")


class LcQuad1Format(_JsonListFormat):
    name = "LC-QuAD 1.0"
    description = "JSON list with `corrected_question` and `sparql_query` (also VQuAnDa/ParaQA)"
    example = (
        '[{"_id": "1501", "corrected_question": "How many movies …?", '
        '"sparql_query": "SELECT …"}]'
    )
    question_keys = ("corrected_question", "intermediary_question", "verbalized_question")
    query_keys = ("sparql_query",)


class RubqFormat(_JsonListFormat):
    name = "RuBQ"
    description = "JSON list with `question_text` (Russian), `question_eng` and `query`"
    example = (
        '[{"uid": 4, "question_text": "Какой …?", "question_eng": "What …?", '
        '"query": "SELECT …"}]'
    )
    question_keys = ("question_text", "question_eng")
    query_keys = ("query",)

    def parse(self, text, data):
        records = super().parse(text, data)
        for r in records:
            if r.raw.get("question_text") and r.language == "en":
                r.language = "ru"
        return records


class GrailQaFormat(_JsonListFormat):
    name = "GrailQA"
    description = "JSON list with `question` and `sparql_query` (Freebase)"
    example = '[{"qid": "2100", "question": "what is …?", "sparql_query": "SELECT …"}]'
    question_keys = ("question",)
    query_keys = ("sparql_query",)


class QuestionSparqlListFormat(_JsonListFormat):
    name = "JSON list (question + sparql)"
    description = (
        "JSON list with `question` and `sparql` keys — covers KQA Pro, "
        "ComplexWebQuestions, CFQ exports and similar"
    )
    example = '[{"question": "Which town …?", "sparql": "SELECT …"}]'
    question_keys = ("question", "machine_question", "questionWithBrackets")
    query_keys = ("sparql", "sparqlPatternModEntities")


class DynBenchFlatFormat(_JsonListFormat):
    name = "DynBench JSON"
    description = (
        "flat JSON list with `question` and `query` (+ optional `id`, "
        "`language`) as used by the bundled DynQALD/DynRuBQ samples"
    )
    example = (
        '[{"id": "train:1", "language": "en", "question": "List all …", '
        '"query": "SELECT …"}]'
    )
    question_keys = ("question", "question_text", "nl_question", "text")
    query_keys = ("query", "sparql", "sparql_query", "target")

    def export(self, results):
        out = []
        for r in results:
            if r.new_question is None:
                continue
            item = copy.deepcopy(r.record.raw)
            for k in self.question_keys:
                if isinstance(item.get(k), str):
                    item[k] = r.new_question
                    break
            for k in self.query_keys:
                if isinstance(item.get(k), str):
                    item[k] = r.new_query
                    break
            # drop stale precomputed transformations of the original pair
            for stale in ("new question", "new query", "old pagerank", "new pagerank"):
                item.pop(stale, None)
            out.append(item)
        return _json_dump(out)


# --- CSV / TSV -----------------------------------------------------------------

_QUESTION_COLS = ("question", "question_text", "nl_question", "corrected_question", "text", "nl")
_QUERY_COLS = ("query", "sparql", "sparql_query", "sparql_wikidata", "target")


class CsvFormat(BenchmarkFormat):
    name = "CSV / TSV"
    description = (
        "delimited text with a header naming a question column "
        "(`question`, `nl_question`, …) and a SPARQL column (`query`, "
        "`sparql`, …) — e.g. Spider4SPARQL's `dev_nl_sparql.csv`"
    )
    example = "question,query\nHow many singers do we have?,SELECT (count(*) …)"

    @staticmethod
    def _sniff(text: str):
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            class _D(csv.excel):
                pass
            _D.delimiter = "\t" if "\t" in sample.split("\n", 1)[0] else ","
            dialect = _D
        return dialect

    def _columns(self, header: list[str]):
        lower = [h.strip().lower() for h in header]
        q_col = next((h for h in _QUESTION_COLS if h in lower), None)
        s_col = next((h for h in _QUERY_COLS if h in lower), None)
        if q_col is None or s_col is None:
            return None, None
        return header[lower.index(q_col)], header[lower.index(s_col)]

    def matches(self, filename, text, data):
        if data is not None or not text.strip():
            return False
        if not filename.lower().endswith((".csv", ".tsv", ".txt")):
            return False
        reader = csv.reader(io.StringIO(text), self._sniff(text))
        header = next(reader, None)
        if not header:
            return False
        return self._columns(header) != (None, None)

    def parse(self, text, data):
        dialect = self._sniff(text)
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        q_col, s_col = self._columns(reader.fieldnames or [])
        records = []
        for i, row in enumerate(reader):
            question, query = (row.get(q_col) or "").strip(), (row.get(s_col) or "").strip()
            if not question or not query:
                continue
            rec_id = (row.get("id") or row.get("uid") or str(i)).strip()
            records.append(
                BenchmarkRecord(
                    id=rec_id, question=question, query=query,
                    raw={"row": row, "q_col": q_col, "s_col": s_col,
                         "fieldnames": reader.fieldnames, "delimiter": dialect.delimiter},
                )
            )
        return records

    def export(self, results):
        done = [r for r in results if r.new_question is not None]
        if not done:
            return ""
        meta = done[0].record.raw
        out = io.StringIO()
        writer = csv.DictWriter(
            out, fieldnames=meta["fieldnames"], delimiter=meta["delimiter"],
            lineterminator="\n",
        )
        writer.writeheader()
        for r in done:
            row = dict(r.record.raw["row"])
            row[meta["q_col"]] = r.new_question
            row[meta["s_col"]] = r.new_query
            writer.writerow(row)
        return out.getvalue()


# --- SPARQL file with comment question (Bio-SODA style) -------------------------

class SparqlCommentFormat(BenchmarkFormat):
    name = "SPARQL file (.rq/.sparql)"
    description = (
        "a single SPARQL query whose leading `#` comment lines contain the "
        "natural-language question (Bio-SODA benchmark style) — one pair per file"
    )
    example = "#the scientific name of species in bgee\nPREFIX up:<…>\nSELECT * {…}"

    def matches(self, filename, text, data):
        if data is not None:
            return False
        if not filename.lower().endswith((".rq", ".sparql")):
            return False
        return bool(re.search(r"\b(SELECT|ASK|CONSTRUCT|DESCRIBE)\b", text, re.IGNORECASE))

    def parse(self, text, data):
        comment_lines, query_lines = [], []
        for line in text.splitlines():
            if line.strip().startswith("#") and not query_lines:
                comment_lines.append(line.strip().lstrip("#").strip())
            else:
                query_lines.append(line)
        question = " ".join(c for c in comment_lines if c)
        query = "\n".join(query_lines).strip()
        if not question or not query:
            return []
        return [BenchmarkRecord(id="1", question=question, query=query, raw=text)]

    def export(self, results):
        parts = []
        for r in results:
            if r.new_question is None:
                continue
            parts.append(f"#{r.new_question}\n{r.new_query}\n")
        return "\n".join(parts)


# --- SIB sparql-examples Turtle --------------------------------------------------

class SibTurtleFormat(BenchmarkFormat):
    name = "SIB sparql-examples (Turtle)"
    description = (
        "Turtle files of the SIB sparql-examples collection: the question in "
        "`rdfs:comment` and the query in `sh:select`/`sh:ask` triple-quoted strings"
    )
    example = (
        '@prefix sh: <http://www.w3.org/ns/shacl#> .\n[] rdfs:comment '
        '"List the proteins …" ;\n  sh:select """SELECT …""" .'
    )

    _COMMENT_RE = re.compile(r'rdfs:comment\s+"""(.*?)"""|rdfs:comment\s+"((?:[^"\\]|\\.)*)"', re.DOTALL)
    _QUERY_RE = re.compile(r"sh:(?:select|ask|construct|describe)\s+'''(.*?)'''|sh:(?:select|ask|construct|describe)\s+\"\"\"(.*?)\"\"\"", re.DOTALL)

    def matches(self, filename, text, data):
        if data is not None:
            return False
        if not filename.lower().endswith((".ttl", ".turtle")):
            return False
        return bool(self._COMMENT_RE.search(text) and self._QUERY_RE.search(text))

    def parse(self, text, data):
        c = self._COMMENT_RE.search(text)
        q = self._QUERY_RE.search(text)
        if not c or not q:
            return []
        question = (c.group(1) or c.group(2) or "").strip().replace('\\"', '"')
        query = (q.group(1) or q.group(2) or "").strip()
        if not question or not query:
            return []
        return [BenchmarkRecord(id="1", question=question, query=query, raw=text)]

    def export(self, results):
        parts = []
        for r in results:
            if r.new_question is None:
                continue
            original = r.record.raw
            out = self._COMMENT_RE.sub(
                f'rdfs:comment """{r.new_question}"""', original, count=1
            )
            out = self._QUERY_RE.sub(
                lambda m: f'sh:select """{r.new_query}"""', out, count=1
            )
            parts.append(out)
        return "\n".join(parts)


# --- registry --------------------------------------------------------------------

# Order matters: most specific first; DynBenchFlatFormat and
# QuestionSparqlListFormat act as increasingly generic JSON-list fallbacks.
FORMATS: list[BenchmarkFormat] = [
    QaldJsonFormat(),
    WebQspFormat(),
    QaldXmlFormat(),
    LcQuad1Format(),
    LcQuad2Format(),
    RubqFormat(),
    GrailQaFormat(),
    QuestionSparqlListFormat(),
    DynBenchFlatFormat(),
    CsvFormat(),
    SparqlCommentFormat(),
    SibTurtleFormat(),
]


def detect_format(filename: str, content: bytes) -> tuple[Optional[BenchmarkFormat], Optional[str]]:
    """Return (format, decoded_text); (None, text_or_None) if nothing matches."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("latin-1")
        except UnicodeDecodeError:
            return None, None
    data = None
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
    for fmt in FORMATS:
        try:
            if fmt.matches(filename, text, data):
                return fmt, text
        except Exception:  # a broken detector must not break the others
            logger.exception("Format detector %s failed", fmt.name)
    return None, text


# Static, user-input-free error messages keyed by error code. API handlers
# must respond with a lookup into this table (not with strings travelling in
# tuples next to request data — taint trackers merge tuple elements).
PARSE_ERROR_MESSAGES = {
    "unrecognized-format": (
        "Unsupported or unrecognized benchmark format. "
        "See the list of supported formats on the upload form."
    ),
    "no-pairs": (
        "The file was recognized as a supported benchmark format but "
        "contains no usable question-query pairs."
    ),
}


def try_parse_benchmark(filename: str, content: bytes):
    """Detect the format and parse without raising.

    Returns (format, records, error_code): on success error_code is None; on
    failure it is a key of PARSE_ERROR_MESSAGES.
    """
    fmt, text = detect_format(filename, content)
    if fmt is None:
        return None, [], "unrecognized-format"
    data = None
    stripped = (text or "").lstrip()
    if stripped.startswith(("{", "[")):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
    records = fmt.parse(text, data)
    if not records:
        return fmt, [], "no-pairs"
    return fmt, records, None


def parse_benchmark(filename: str, content: bytes):
    """Detect the format and parse. Returns (format, records) or raises ValueError."""
    fmt, records, error_code = try_parse_benchmark(filename, content)
    if error_code == "no-pairs":
        raise ValueError(
            f"The file was recognized as '{fmt.name}' but contains no usable "
            "question-query pairs."
        )
    if error_code is not None:
        raise ValueError(PARSE_ERROR_MESSAGES[error_code])
    return fmt, records
