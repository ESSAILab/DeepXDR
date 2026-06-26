from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np
from openai import AsyncOpenAI, OpenAI

from mitreattack.stix20 import MitreAttackData

logger = logging.getLogger(__name__)

ATTACK_VERSION = "18.1"
DEFAULT_EMBEDDING_MODEL = "text-embedding-v4"
DEFAULT_RERANKER_MODEL = "qwen3-rerank"
DEFAULT_EMBEDDING_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_RERANK_BASE_URL = "https://dashscope.aliyuncs.com/compatible-api/v1"


@dataclass(frozen=True)
class TechniqueDocument:
    attack_id: str
    stix_id: str
    name: str
    description: str
    is_subtechnique: bool
    platforms: List[str]
    tactic_shortnames: List[str]
    url: Optional[str]
    procedure_examples: List[str]
    search_text: str

    def to_confirmed_dict(self, tactics: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "id": self.attack_id,
            "name": self.name,
            "stix_id": self.stix_id,
            "description": self.description,
            "is_subtechnique": self.is_subtechnique,
            "platforms": self.platforms,
            "url": self.url,
            "tactics": tactics,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TechniqueDocument":
        return cls(
            attack_id=str(data["attack_id"]),
            stix_id=str(data["stix_id"]),
            name=str(data["name"]),
            description=str(data.get("description") or ""),
            is_subtechnique=bool(data.get("is_subtechnique")),
            platforms=[str(x) for x in data.get("platforms", [])],
            tactic_shortnames=[str(x) for x in data.get("tactic_shortnames", [])],
            url=data.get("url"),
            procedure_examples=[str(x) for x in data.get("procedure_examples", [])],
            search_text=str(data.get("search_text") or ""),
        )


@dataclass(frozen=True)
class BehaviorEvidence:
    evidence: str
    behavior: str
    event_ids: List[str]


@dataclass(frozen=True)
class BehaviorExtractionResult:
    triage_summary: str
    behaviors: List[BehaviorEvidence]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _mitre_cache_dir() -> Path:
    cache_dir = os.getenv("MITRE_ATTACK_CACHE_DIR")
    if cache_dir:
        return Path(cache_dir)
    return _package_root() / ".cache" / "mitre_attack"


def _default_stix_path() -> Path:
    root = _repo_root()
    candidates = [
        root / "ai_agent" / "data" / f"v{ATTACK_VERSION}" / "enterprise-attack.json",
        root / "data" / f"v{ATTACK_VERSION}" / "enterprise-attack.json",
        root / "attack-releases" / "stix-2.0" / f"v{ATTACK_VERSION}" / "enterprise-attack.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "ATT&CK Enterprise STIX v18.1 file not found. Expected one of: "
        + ", ".join(str(p) for p in candidates)
    )


def _external_id_and_url(obj: Any) -> tuple[Optional[str], Optional[str]]:
    for ref in _field(obj, "external_references", []) or []:
        if _field(ref, "source_name") == "mitre-attack":
            return _field(ref, "external_id"), _field(ref, "url")
    return None, None


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _relationship_object(item: Any) -> Any:
    if isinstance(item, dict):
        return item.get("object") or item.get("target") or item
    return getattr(item, "object", None) or item


def _object_summary(obj: Any, include_description: bool = False) -> Dict[str, Any]:
    attack_id, url = _external_id_and_url(obj)
    data = {
        "attack_id": attack_id,
        "id": attack_id,
        "name": _field(obj, "name"),
        "stix_id": _field(obj, "id"),
        "url": url,
    }
    if include_description:
        data["description"] = _field(obj, "description")
    return data


def _clean_text(text: str, max_chars: int = 1200) -> str:
    compact = " ".join((text or "").split())
    return compact[:max_chars] + ("..." if len(compact) > max_chars else "")


def _dedupe(items: Iterable[str], limit: int) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        value = str(item or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
        if len(out) >= limit:
            break
    return out


def _normalize_triage_summary(summary: str, max_chars: int = 600) -> str:
    compact = " ".join((summary or "").split())
    if not compact:
        return "\u5f53\u524d\u7a97\u53e3\u5305\u542b\u7591\u4f3c\u653b\u51fb\u76f8\u5173\u4e8b\u4ef6\uff0c\u9700\u7ed3\u5408\u539f\u59cb\u65e5\u5fd7\u8fdb\u4e00\u6b65\u5206\u6790\u3002"
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 1].rstrip("\uff0c\uff1b\u3001\u3002 ") + "\u3002"


class AttackKnowledgeBase:
    def __init__(
        self,
        stix_path: Optional[str | Path] = None,
        include_procedure_examples: bool = True,
    ):
        self.stix_path = Path(stix_path) if stix_path else _default_stix_path()
        self.include_procedure_examples = include_procedure_examples
        self.attack = MitreAttackData(str(self.stix_path))
        cached = self._load_catalog_cache()
        if cached:
            self.tactic_by_shortname = cached["tactic_by_shortname"]
            self.catalog = cached["catalog"]
        else:
            self.tactic_by_shortname = self._build_tactic_map()
            self.catalog = self._build_technique_catalog()
            self._write_catalog_cache()
        self.by_id = {item.attack_id: item for item in self.catalog}
        self.by_stix_id = {item.stix_id: item for item in self.catalog}

    def _catalog_cache_path(self) -> Path:
        proc_tag = "with_procedures" if self.include_procedure_examples else "no_procedures"
        return _mitre_cache_dir() / f"catalog_{ATTACK_VERSION}_{proc_tag}.json"

    def _catalog_cache_candidates(self) -> List[Path]:
        primary = self._catalog_cache_path()
        proc_tag = "with_procedures" if self.include_procedure_examples else "no_procedures"
        legacy = sorted(
            primary.parent.glob(f"catalog_{ATTACK_VERSION}_*_{proc_tag}.json"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        return [primary] + [path for path in legacy if path != primary]

    def _load_catalog_cache(self) -> Optional[Dict[str, Any]]:
        for cache_path in self._catalog_cache_candidates():
            if not cache_path.exists():
                continue
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                if data.get("attack_version") != ATTACK_VERSION:
                    continue
                if data.get("include_procedure_examples") != self.include_procedure_examples:
                    continue
                catalog = [TechniqueDocument.from_dict(item) for item in data["catalog"]]
                tactic_by_shortname = data["tactic_by_shortname"]
                if not isinstance(tactic_by_shortname, dict):
                    continue
                if cache_path != self._catalog_cache_path():
                    self._catalog_cache_path().write_text(
                        json.dumps(data, ensure_ascii=False),
                        encoding="utf-8",
                    )
                return {
                    "catalog": catalog,
                    "tactic_by_shortname": tactic_by_shortname,
                }
            except Exception as exc:
                logger.warning("Failed to load ATT&CK catalog cache %s: %s", cache_path, exc)
        return None

    def _write_catalog_cache(self) -> None:
        cache_path = self._catalog_cache_path()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "attack_version": ATTACK_VERSION,
            "stix_path": str(self.stix_path),
            "include_procedure_examples": self.include_procedure_examples,
            "tactic_by_shortname": self.tactic_by_shortname,
            "catalog": [asdict(item) for item in self.catalog],
        }
        try:
            cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to write ATT&CK catalog cache %s: %s", cache_path, exc)

    def _build_tactic_map(self) -> Dict[str, Dict[str, Any]]:
        tactics: Dict[str, Dict[str, Any]] = {}
        for tactic in self.attack.get_tactics_by_matrix().get("Enterprise ATT&CK", []):
            if _field(tactic, "revoked", False) or _field(tactic, "x_mitre_deprecated", False):
                continue
            attack_id, url = _external_id_and_url(tactic)
            shortname = _field(tactic, "x_mitre_shortname")
            tactics[shortname] = {
                "tactic": shortname,
                "tactic_id": attack_id,
                "name": _field(tactic, "name"),
                "url": url,
            }
        return tactics

    def _procedure_examples(self, stix_id: str, limit: int = 6) -> List[str]:
        try:
            rels = self.attack.get_procedure_examples_by_technique(stix_id)
        except Exception:
            return []
        examples = []
        for rel in rels or []:
            desc = _field(rel, "description", "")
            if desc:
                examples.append(_clean_text(desc, max_chars=500))
        return _dedupe(examples, limit)

    def _build_technique_catalog(self) -> List[TechniqueDocument]:
        docs: List[TechniqueDocument] = []
        techniques = self.attack.get_techniques(
            include_subtechniques=True,
            remove_revoked_deprecated=True,
        )
        for tech in techniques:
            attack_id, url = _external_id_and_url(tech)
            if not attack_id:
                continue
            tactic_shortnames = [
                _field(phase, "phase_name")
                for phase in _field(tech, "kill_chain_phases", []) or []
                if _field(phase, "kill_chain_name") == "mitre-attack"
            ]
            description = _field(tech, "description", "") or ""
            platforms = list(_field(tech, "x_mitre_platforms", []) or [])
            procedures = (
                self._procedure_examples(_field(tech, "id"), limit=6)
                if self.include_procedure_examples
                else []
            )
            search_text = "\n".join(
                [
                    f"ID: {attack_id}",
                    f"Name: {_field(tech, 'name')}",
                    f"Description: {description}",
                    f"Tactics: {', '.join(tactic_shortnames)}",
                    f"Platforms: {', '.join(platforms)}",
                    "Procedure examples: " + " ".join(procedures),
                ]
            )
            docs.append(
                TechniqueDocument(
                    attack_id=attack_id,
                    stix_id=_field(tech, "id"),
                    name=_field(tech, "name"),
                    description=description,
                    is_subtechnique=bool(_field(tech, "x_mitre_is_subtechnique", False)),
                    platforms=platforms,
                    tactic_shortnames=tactic_shortnames,
                    url=url,
                    procedure_examples=procedures,
                    search_text=search_text,
                )
            )
        return docs

    def tactics_for(self, doc: TechniqueDocument) -> List[Dict[str, Any]]:
        return [
            self.tactic_by_shortname[s]
            for s in doc.tactic_shortnames
            if s in self.tactic_by_shortname
        ]

    def confirm_techniques(self, technique_ids: Sequence[str]) -> Dict[str, Any]:
        confirmed: List[Dict[str, Any]] = []
        not_found: List[str] = []
        seen = set()
        for technique_id in technique_ids:
            tid = str(technique_id).strip()
            if not tid or tid in seen:
                continue
            seen.add(tid)
            doc = self.by_id.get(tid)
            if not doc:
                not_found.append(tid)
                continue
            confirmed.append(doc.to_confirmed_dict(self.tactics_for(doc)))
        return {
            "domain": "enterprise",
            "attack_version": ATTACK_VERSION,
            "confirmed_techniques": confirmed,
            "not_found": not_found,
        }

    def enrich_intel(self, confirmed: List[Dict[str, Any]], max_items: int = 5) -> Dict[str, Any]:
        rows: List[Dict[str, Any]] = []
        for tech in confirmed:
            stix_id = tech.get("stix_id")
            if not stix_id:
                continue
            groups = [
                _object_summary(_relationship_object(item), include_description=False)
                for item in self.attack.get_groups_using_technique(stix_id)
            ][:max_items]
            software = [
                _object_summary(_relationship_object(item), include_description=False)
                for item in self.attack.get_software_using_technique(stix_id)
            ][:max_items]
            rows.append(
                {
                    "technique": {
                        "id": tech.get("id"),
                        "name": tech.get("name"),
                        "stix_id": stix_id,
                    },
                    "groups_using_technique": groups,
                    "software_using_technique": software,
                }
            )
        return {"domain": "enterprise", "intel": rows}

    def enrich_detections(self, confirmed: List[Dict[str, Any]], max_items: int = 7) -> Dict[str, Any]:
        rows: List[Dict[str, Any]] = []
        for tech in confirmed:
            stix_id = tech.get("stix_id")
            doc = self.by_stix_id.get(stix_id)
            if not stix_id or not doc:
                continue
            components = [
                _object_summary(_relationship_object(item), include_description=False)
                for item in self.attack.get_datacomponents_detecting_technique(stix_id)
            ]
            names = _dedupe([c.get("name", "") for c in components], max_items)
            rows.append(
                {
                    "technique": {
                        "id": tech.get("id"),
                        "name": tech.get("name"),
                        "stix_id": stix_id,
                    },
                    "detection": {
                        "mode": "datacomponents" if names else "technique_context",
                        "total_datacomponents": len(components),
                        "top_datacomponents": names,
                        "platforms": doc.platforms,
                        "note": (
                            "No ATT&CK data component relationships were present in v18.1; "
                            "use platform and procedure context for LLM fallback."
                            if not names
                            else ""
                        ),
                    },
                }
            )
        return {"domain": "enterprise", "detections": rows}

    def enrich_mitigations(
        self,
        confirmed: List[Dict[str, Any]],
        include_description: bool = False,
    ) -> Dict[str, Any]:
        rows: List[Dict[str, Any]] = []
        for tech in confirmed:
            stix_id = tech.get("stix_id")
            if not stix_id:
                continue
            mitigations = [
                _object_summary(_relationship_object(item), include_description=include_description)
                for item in self.attack.get_mitigations_mitigating_technique(stix_id)
            ]
            rows.append(
                {
                    "technique": {
                        "id": tech.get("id"),
                        "name": tech.get("name"),
                        "stix_id": stix_id,
                    },
                    "found": bool(mitigations),
                    "count": len(mitigations),
                    "mitigations": mitigations,
                    "formatted": ", ".join(m.get("name", "") for m in mitigations if m.get("name")),
                    "message": "" if mitigations else "No mitigations found in ATT&CK v18.1.",
                }
            )
        return {
            "domain": "enterprise",
            "mitigations": rows,
            "errors": [],
            "summary": {
                "total_techniques": len(confirmed),
                "with_mitigations": sum(1 for row in rows if row.get("count", 0) > 0),
                "total_mitigations": sum(row.get("count", 0) for row in rows),
            },
        }


class DashScopeEmbeddingRerankRetriever:
    def __init__(
        self,
        catalog: Sequence[TechniqueDocument],
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        reranker_model: str = DEFAULT_RERANKER_MODEL,
        api_key: Optional[str] = None,
        embedding_base_url: str = DEFAULT_EMBEDDING_BASE_URL,
        rerank_base_url: str = DEFAULT_RERANK_BASE_URL,
        cache_tag: str = "with_procedures",
    ):
        self.catalog = list(catalog)
        self.embedding_model = embedding_model
        self.reranker_model = reranker_model
        self.cache_tag = cache_tag
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is required for DashScope embedding/rerank retrieval")
        self.embedding_client = OpenAI(api_key=self.api_key, base_url=embedding_base_url)
        self.rerank_client = OpenAI(api_key=self.api_key, base_url=rerank_base_url)
        self.doc_embeddings = self._load_or_create_doc_embeddings()
        self.doc_embeddings = _normalize_matrix(self.doc_embeddings)

    def retrieve(self, query: str, recall_k: int = 50, rerank_k: int = 8) -> List[Dict[str, Any]]:
        query_embedding = np.array(self._embed_texts([query])[0], dtype=np.float32)
        query_embedding = _normalize_vector(query_embedding)
        scores = np.dot(self.doc_embeddings, query_embedding)
        recall_indices = np.argsort(scores)[::-1][:recall_k]
        rerank_scores = self._rerank(
            query,
            [self.catalog[int(idx)].search_text for idx in recall_indices],
            top_n=min(rerank_k, len(recall_indices)),
        )

        ranked = []
        for reranked in rerank_scores:
            local_idx = int(reranked["index"])
            catalog_idx = int(recall_indices[local_idx])
            ranked.append(
                (
                    catalog_idx,
                    float(scores[catalog_idx]),
                    float(reranked.get("relevance_score", reranked.get("score", 0.0))),
                )
            )
        return [
            {
                "technique": self.catalog[int(idx)],
                "embedding_score": float(embedding_score),
                "rerank_score": float(rerank_score),
            }
            for idx, embedding_score, rerank_score in ranked
        ]

    def _embed_texts(self, texts: Sequence[str], batch_size: int = 10) -> List[List[float]]:
        embeddings: List[List[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = list(texts[start : start + batch_size])
            response = self.embedding_client.embeddings.create(
                model=self.embedding_model,
                input=batch,
            )
            ordered = sorted(response.data, key=lambda item: item.index)
            embeddings.extend([item.embedding for item in ordered])
        return embeddings

    def _load_or_create_doc_embeddings(self) -> np.ndarray:
        cache_path = _embedding_cache_path(self.embedding_model, self.cache_tag)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        if cache_path.exists():
            try:
                return np.load(cache_path)
            except Exception as exc:
                logger.warning("Failed to load ATT&CK embedding cache %s: %s", cache_path, exc)
        legacy_cache_path = _legacy_embedding_cache_path(self.embedding_model, self.catalog)
        if legacy_cache_path.exists():
            try:
                embeddings = np.load(legacy_cache_path)
                np.save(cache_path, embeddings)
                return embeddings
            except Exception as exc:
                logger.warning("Failed to migrate legacy ATT&CK embedding cache %s: %s", legacy_cache_path, exc)
        embeddings = np.array(
            self._embed_texts([doc.search_text for doc in self.catalog]),
            dtype=np.float32,
        )
        try:
            np.save(cache_path, embeddings)
        except Exception as exc:
            logger.warning("Failed to write ATT&CK embedding cache %s: %s", cache_path, exc)
        return embeddings

    def _rerank(self, query: str, documents: Sequence[str], top_n: int) -> List[Dict[str, Any]]:
        response = self.rerank_client.post(
            "/reranks",
            body={
                "model": self.reranker_model,
                "query": query,
                "documents": list(documents),
                "top_n": top_n,
            },
            cast_to=object,
        )
        if isinstance(response, dict):
            results = response.get("results") or response.get("output", {}).get("results") or []
        else:
            results = getattr(response, "results", None) or []
        if not isinstance(results, list):
            raise ValueError(f"Unexpected rerank response shape: {response!r}")
        return results


def _normalize_vector(vector: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vector)
    if norm == 0:
        return vector
    return vector / norm


def _normalize_matrix(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def _embedding_cache_path(model: str, cache_tag: str) -> Path:
    safe_model = re.sub(r"[^A-Za-z0-9_.-]+", "_", model)
    safe_tag = re.sub(r"[^A-Za-z0-9_.-]+", "_", cache_tag)
    return _mitre_cache_dir() / f"{safe_model}_{ATTACK_VERSION}_{safe_tag}.npy"


def _legacy_embedding_cache_path(model: str, catalog: Sequence[TechniqueDocument]) -> Path:
    safe_model = re.sub(r"[^A-Za-z0-9_.-]+", "_", model)
    fingerprint = f"{ATTACK_VERSION}_{len(catalog)}_{sum(len(doc.search_text) for doc in catalog)}"
    return _mitre_cache_dir() / f"{safe_model}_{fingerprint}.npy"


class OpenAIFinalTechniqueJudge:
    def __init__(self, model: Optional[str] = None):
        self.model = model or os.getenv("MITRE_RAG_LLM_MODEL", "gpt-4.1-mini")
        self.client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL"),
            timeout=180.0,
        )

    async def extract_window_context(self, incident_text: str) -> BehaviorExtractionResult:
        prompt = {
            "task": "Summarize an incident window and extract atomic adversary behavior evidence from it.",
            "rules": [
                "Return triage_summary in Chinese language, no more than 600 characters.",
                "triage_summary must summarize all events in the current window, including attack behavior, affected assets, sequence, accounts, processes, files, commands, or network indicators when present.",
                "Keep triage_summary concise and informative.",
                "Do not summarize ATT&CK mapping statistics in triage_summary.",
                "Do not invent facts not present in incident_text.",
                "Extract concrete adversary behaviors only.",
                "Keep evidence close to the original text.",
                "Do not map to MITRE ATT&CK yet.",
                "If event IDs are present, include them.",
            ],
            "output_schema": {
                "triage_summary": "Chinese summary string <= 600 chars",
                "behaviors": [
                    {"evidence": "string", "behavior": "English normalized behavior", "event_ids": ["string"]}
                ]
            },
            "incident_text": incident_text,
        }
        raw = await self._json_chat(prompt, temperature=0.1)
        triage_summary = _normalize_triage_summary(
            str(raw.get("triage_summary") or raw.get("summary") or "")
            if isinstance(raw, dict)
            else ""
        )
        behaviors = raw.get("behaviors", []) if isinstance(raw, dict) else []
        out = []
        for item in behaviors:
            if not isinstance(item, dict):
                continue
            evidence = str(item.get("evidence") or item.get("behavior") or "").strip()
            behavior = str(item.get("behavior") or evidence).strip()
            if evidence and behavior:
                out.append(
                    BehaviorEvidence(
                        evidence=evidence,
                        behavior=behavior,
                        event_ids=[str(x) for x in item.get("event_ids", []) if x],
                    )
                )
        return BehaviorExtractionResult(triage_summary=triage_summary, behaviors=out)

    async def extract_behaviors(self, incident_text: str) -> List[BehaviorEvidence]:
        return (await self.extract_window_context(incident_text)).behaviors

    async def judge(
        self,
        behavior: BehaviorEvidence,
        candidates: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        candidate_payload = []
        for idx, item in enumerate(candidates, start=1):
            doc: TechniqueDocument = item["technique"]
            candidate_payload.append(
                {
                    "rank": idx,
                    "attack_id": doc.attack_id,
                    "name": doc.name,
                    "description": _clean_text(doc.description, max_chars=900),
                    "tactics": doc.tactic_shortnames,
                    "platforms": doc.platforms,
                    "procedure_examples": doc.procedure_examples[:3],
                    "rerank_score": item.get("rerank_score"),
                }
            )
        prompt = {
            "task": "Map one threat-report behavior to MITRE ATT&CK Enterprise techniques.",
            "evidence": behavior.evidence,
            "normalized_behavior": behavior.behavior,
            "candidate_techniques": candidate_payload,
            "rules": [
                "Select only attack_id values from candidate_techniques.",
                "Prefer a sub-technique when the evidence is specific enough.",
                "Return an empty matches list if none are directly supported.",
                "Do not invent IDs, names, or facts.",
            ],
            "output_schema": {
                "matches": [
                    {"attack_id": "Txxxx or Txxxx.xxx", "confidence": 0.0, "reason": "string"}
                ]
            },
        }
        raw = await self._json_chat(prompt, temperature=0.0)
        matches = raw.get("matches", []) if isinstance(raw, dict) else []
        return [m for m in matches if isinstance(m, dict)]

    async def _json_chat(self, payload: Dict[str, Any], temperature: float) -> Dict[str, Any]:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for LLM behavior extraction/final judgement")
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "Return only valid JSON. You are precise and evidence-bound.",
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "temperature": temperature,
        }
        if self.model.startswith(("gpt-", "o1", "o3")):
            kwargs["response_format"] = {"type": "json_object"}
        response = await self.client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or "{}"
        content = _strip_json(content)
        return json.loads(content)


def _strip_json(raw: str) -> str:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


class AttackRagService:
    def __init__(
        self,
        kb: Optional[AttackKnowledgeBase] = None,
        retriever: Optional[Any] = None,
        judge: Optional[Any] = None,
    ):
        self.kb = kb or AttackKnowledgeBase()
        cache_tag = "with_procedures" if self.kb.include_procedure_examples else "no_procedures"
        self.retriever = retriever or DashScopeEmbeddingRerankRetriever(self.kb.catalog, cache_tag=cache_tag)
        self.judge = judge or OpenAIFinalTechniqueJudge()

    async def map_report_to_techniques(
        self,
        incident_text: str,
        recall_k: int = 50,
        rerank_k: int = 8,
    ) -> Dict[str, Any]:
        if hasattr(self.judge, "extract_window_context"):
            extraction = await self.judge.extract_window_context(incident_text)
            behaviors = extraction.behaviors
            triage_summary = extraction.triage_summary
        else:
            behaviors = await self.judge.extract_behaviors(incident_text)
            triage_summary = _normalize_triage_summary("")
        if not behaviors:
            raise ValueError("No concrete adversary behaviors extracted from incident text")

        by_id: Dict[str, Dict[str, Any]] = {}
        candidate_debug: Dict[str, List[Dict[str, Any]]] = {}
        unmapped: List[Dict[str, Any]] = []

        for behavior in behaviors:
            hits = self.retriever.retrieve(behavior.behavior, recall_k=recall_k, rerank_k=rerank_k)
            candidate_debug[behavior.behavior] = [
                {
                    "attack_id": item["technique"].attack_id,
                    "name": item["technique"].name,
                    "embedding_score": item.get("embedding_score"),
                    "rerank_score": item.get("rerank_score"),
                }
                for item in hits
            ]
            matches = await self.judge.judge(behavior, hits)
            accepted = False
            for match in matches:
                attack_id = str(match.get("attack_id", "")).strip()
                official = self.kb.by_id.get(attack_id)
                if not official:
                    continue
                row = by_id.setdefault(
                    attack_id,
                    {
                        "id": official.attack_id,
                        "name": official.name,
                        "stix_id": official.stix_id,
                        "description": official.description,
                        "is_subtechnique": official.is_subtechnique,
                        "platforms": official.platforms,
                        "url": official.url,
                        "tactics": self.kb.tactics_for(official),
                        "evidence": [],
                        "procedures": [],
                        "event_ids": [],
                        "confidence": 0.0,
                        "reason": "",
                    },
                )
                row["evidence"].append(behavior.evidence)
                row["procedures"].append(behavior.behavior)
                row["event_ids"].extend(behavior.event_ids)
                row["event_ids"] = _dedupe(row["event_ids"], 20)
                row["confidence"] = max(row["confidence"], float(match.get("confidence") or 0.0))
                if match.get("reason"):
                    row["reason"] = str(match["reason"])
                accepted = True
            if not accepted:
                unmapped.append(
                    {
                        "evidence": behavior.evidence,
                        "behavior": behavior.behavior,
                        "event_ids": behavior.event_ids,
                    }
                )

        confirmed = sorted(by_id.values(), key=lambda item: item["confidence"], reverse=True)
        return {
            "triage_summary": triage_summary,
            "technique_ids": [item["id"] for item in confirmed],
            "technique_candidates": {item["id"]: item["evidence"] for item in confirmed},
            "technique_events": {item["id"]: item["event_ids"] for item in confirmed if item["event_ids"]},
            "confirmed_techniques": confirmed,
            "unmapped_behaviors": unmapped,
            "retrieval_candidates": candidate_debug,
            "attack_version": ATTACK_VERSION,
        }

    def confirm_techniques(self, technique_ids: Sequence[str]) -> Dict[str, Any]:
        return self.kb.confirm_techniques(technique_ids)

    def enrich_intel(self, confirmed: List[Dict[str, Any]], max_items: int = 5) -> Dict[str, Any]:
        return self.kb.enrich_intel(confirmed, max_items=max_items)

    def enrich_detections(self, confirmed: List[Dict[str, Any]], max_items: int = 7) -> Dict[str, Any]:
        return self.kb.enrich_detections(confirmed, max_items=max_items)

    def enrich_mitigations(
        self,
        confirmed: List[Dict[str, Any]],
        include_description: bool = False,
    ) -> Dict[str, Any]:
        return self.kb.enrich_mitigations(confirmed, include_description=include_description)


@lru_cache(maxsize=1)
def get_attack_rag_service() -> AttackRagService:
    return AttackRagService()
