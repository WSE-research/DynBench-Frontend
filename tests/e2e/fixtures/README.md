# E2E benchmark-file fixtures

Small subsets (first 1–2 records) extracted from the **original benchmark
files**, preserving the exact file structure, so the end-to-end tests exercise
every supported benchmark file type against the real server. Recreate with:

```bash
python tests/e2e/fixtures/extract_fixtures.py
```

Retrieved 2026-07-12 from the official sources (HuggingFace mirrors are used
where the original download is not directly fetchable):

| Fixture | Original source | License of the source |
|---|---|---|
| `qald-9-test.subset.json` | [ag-sc/QALD](https://github.com/ag-sc/QALD) `9/data/qald-9-test-multilingual.json` | MIT |
| `qald-4-biomedical-train.subset.xml` | [ag-sc/QALD](https://github.com/ag-sc/QALD) `4/data/qald-4_biomedical_train.xml` | MIT |
| `lcquad1-train.subset.json` | [AskNowQA/LC-QuAD](https://github.com/AskNowQA/LC-QuAD) `train-data.json` | GPL-3.0 |
| `lcquad2-test.subset.json` | [AskNowQA/LC-QuAD2.0](https://github.com/AskNowQA/LC-QuAD2.0) `dataset/test.json` | none stated |
| `rubq-2.0-test.subset.json` | [vladislavneon/RuBQ](https://github.com/vladislavneon/RuBQ) `RuBQ_2.0/RuBQ_2.0_test.json` | CC BY-SA 4.0 |
| `grailqa-validation.subset.json` | [HF mirror `Hieuman/grail_qa`](https://huggingface.co/datasets/Hieuman/grail_qa) (official download is JS-gated) | CC BY-SA 4.0 (per homepage) |
| `complexwebquestions-validation.subset.json` | [HF mirror `drt/complex_web_questions`](https://huggingface.co/datasets/drt/complex_web_questions) | unknown |
| `webqsp-test.subset.json` | [Microsoft WebQSP.zip](https://www.microsoft.com/en-us/download/details.aspx?id=52763) `WebQSP.test.json` | Microsoft Research Data License |
| `beastiary-qald-format.subset.json` | [danrd/sparqlgen](https://github.com/danrd/sparqlgen) `beastiary_with_qald_format.json.zip` | none stated |
| `dynqald.subset.json` | bundled `benchmarks/DynQALD.json` (this repository) | project license |
| `spider4sparql-dev.subset.csv` | [ckosten/spider4sparql](https://github.com/ckosten/spider4sparql) `nl_sparql_pairs/dev/dev_nl_sparql.csv` | Apache-2.0 |
| `bio-soda-bgee-q1.rq` | [anazhaw/Bio-SODA](https://github.com/anazhaw/Bio-SODA) `Benchmarks/Bioinformatics/Bgee/Q1.rq` | none stated |
| `sib-uniprot-100.ttl` | [sib-swiss/sparql-examples](https://github.com/sib-swiss/sparql-examples) `examples/UniProt/100_uniprot_organelles_or_plasmids.ttl` | CC BY 4.0 |

The excerpts are used solely as test fixtures for format compatibility, with
attribution above. Note the WebQSP source is under the Microsoft Research
Data License and LC-QuAD 1.0 under GPL-3.0 — replace these two fixtures with
synthetic equivalents if stricter license separation is required.
