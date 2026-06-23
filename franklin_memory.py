from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
WORKFLOW_DIR = BASE_DIR / "agent_workspace"
MEMORY_PATH = WORKFLOW_DIR / "franklin_memory.json"


DEFAULT_MEMORY = {
    "version": 1,
    "updated_at": None,
    "policy": {
        "auto_apply_structured_rules": True,
        "auto_promote_free_text_to_scoring_rule": False,
        "max_total_score_adjustment": 12.0,
    },
    "experiences": [],
    "learned_rules": [
        {
            "id": "default_roi_requires_human_confirmation",
            "created_at": "builtin",
            "active": True,
            "source": "builtin",
            "label": "Default ROI needs confirmation",
            "keywords": [],
            "applies_to_flags": [],
            "applies_to_assumptions": ["using_default_roi_from_config"],
            "score_adjustment": -6.0,
            "recommendation": "This run used the default ROI; confirm ROI before treating the result as final.",
        },
        {
            "id": "default_valid_window_requires_human_confirmation",
            "created_at": "builtin",
            "active": True,
            "source": "builtin",
            "label": "Default valid frame range needs confirmation",
            "keywords": [],
            "applies_to_flags": [],
            "applies_to_assumptions": ["using_default_valid_frame_range_from_config"],
            "score_adjustment": -6.0,
            "recommendation": "This run used the default valid frame range; confirm the valid window before final ranking.",
        },
    ],
    "feedback": [],
    "pending_rule_proposals": [],
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_memory() -> dict[str, Any]:
    WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)
    if not MEMORY_PATH.exists():
        save_memory(DEFAULT_MEMORY)
        return json.loads(json.dumps(DEFAULT_MEMORY))
    with MEMORY_PATH.open("r", encoding="utf-8") as f:
        memory = json.load(f)
    for key, value in DEFAULT_MEMORY.items():
        memory.setdefault(key, json.loads(json.dumps(value)))
    return memory


def save_memory(memory: dict[str, Any]) -> None:
    memory["updated_at"] = now_iso()
    WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)
    with MEMORY_PATH.open("w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2, ensure_ascii=False)


def stable_id(prefix: str, *parts: str) -> str:
    raw = "_".join(parts)
    raw = re.sub(r"\s+", "_", raw.strip())
    raw = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    return f"{prefix}_{raw[:80]}" if raw else f"{prefix}_{now_iso().replace(':', '-')}"


def remember_intake(case_id: str, intake: dict[str, Any] | None) -> dict[str, Any] | None:
    if not intake:
        return None
    subjective = (intake.get("subjective_experience") or "").strip()
    criteria = (intake.get("review_criteria") or "").strip()
    if not subjective and not criteria:
        return None

    memory = load_memory()
    raw_path = intake.get("raw_tiff_path", "")
    item_id = stable_id("exp", case_id, raw_path, subjective[:30], criteria[:30])
    existing = {item.get("id") for item in memory.get("experiences", [])}
    if item_id not in existing:
        memory["experiences"].append(
            {
                "id": item_id,
                "created_at": now_iso(),
                "case_id": case_id,
                "raw_tiff_path": raw_path,
                "subjective_experience": subjective,
                "review_criteria": criteria,
                "status": "active_context",
                "source": "intake",
            }
        )

    if criteria:
        proposal_id = stable_id("proposal", case_id, criteria[:60])
        proposals = {item.get("id") for item in memory.get("pending_rule_proposals", [])}
        if proposal_id not in proposals:
            memory["pending_rule_proposals"].append(
                {
                    "id": proposal_id,
                    "created_at": now_iso(),
                    "case_id": case_id,
                    "source": "intake_review_criteria",
                    "text": criteria,
                    "suggested_next_step": "Ask Codex to convert this free-text criterion into a structured Franklin rule if it should affect scoring.",
                }
            )

    save_memory(memory)
    return {"memory_path": str(MEMORY_PATH), "experience_id": item_id}


def text_blob(metrics: dict[str, Any], review: dict[str, Any]) -> str:
    parts = [
        str(metrics.get("case", "")),
        str(metrics.get("case_id", "")),
        str(metrics.get("subjective_experience", "")),
        str(metrics.get("review_criteria", "")),
        " ".join(metrics.get("assumptions", []) or []),
        " ".join(review.get("flags", []) or []),
    ]
    return " ".join(parts).lower()


def rule_matches(rule: dict[str, Any], metrics: dict[str, Any], review: dict[str, Any]) -> bool:
    if not rule.get("active", False):
        return False
    flags = set(review.get("flags", []) or [])
    assumptions = set(metrics.get("assumptions", []) or [])

    applies_flags = set(rule.get("applies_to_flags", []) or [])
    if applies_flags and not applies_flags.intersection(flags):
        return False

    applies_assumptions = set(rule.get("applies_to_assumptions", []) or [])
    if applies_assumptions and not applies_assumptions.intersection(assumptions):
        return False

    keywords = [str(item).lower() for item in rule.get("keywords", []) or [] if str(item).strip()]
    if keywords:
        blob = text_blob(metrics, review)
        if not any(keyword in blob for keyword in keywords):
            return False

    return bool(applies_flags or applies_assumptions or keywords)


def matching_experiences(case_id: str, metrics: dict[str, Any]) -> list[dict[str, Any]]:
    memory = load_memory()
    case_text = f"{case_id} {metrics.get('case', '')}".lower()
    matches = []
    for item in memory.get("experiences", []):
        if item.get("status") != "active_context":
            continue
        if item.get("case_id") == case_id or str(item.get("case_id", "")).lower() in case_text:
            matches.append(item)
    return matches[-5:]


def band_for_score(score: float) -> str:
    if score >= 85:
        return "excellent"
    if score >= 70:
        return "usable_review"
    if score >= 50:
        return "needs_review"
    return "low_confidence"


def apply_memory_to_review(case_id: str, metrics: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    memory = load_memory()
    review = json.loads(json.dumps(review))
    matched_rules = [
        rule for rule in memory.get("learned_rules", []) if rule_matches(rule, metrics, review)
    ]
    matched_experiences = matching_experiences(case_id, metrics)

    max_adjustment = float(memory.get("policy", {}).get("max_total_score_adjustment", 12.0))
    if memory.get("policy", {}).get("auto_apply_structured_rules", True):
        raw_adjustment = sum(float(rule.get("score_adjustment", 0.0)) for rule in matched_rules)
        score_adjustment = max(-max_adjustment, min(max_adjustment, raw_adjustment))
    else:
        score_adjustment = 0.0

    original_score = float(review.get("reviewer_score", 0.0))
    adjusted_score = max(0.0, min(100.0, original_score + score_adjustment))
    review["reviewer_score_before_memory"] = round(original_score, 1)
    review["memory_score_adjustment"] = round(score_adjustment, 1)
    review["reviewer_score"] = round(adjusted_score, 1)
    review["band"] = band_for_score(adjusted_score)
    review["memory_matches"] = {
        "rules": [
            {
                "id": rule.get("id"),
                "label": rule.get("label"),
                "score_adjustment": rule.get("score_adjustment", 0.0),
                "recommendation": rule.get("recommendation", ""),
            }
            for rule in matched_rules
        ],
        "experiences": [
            {
                "id": item.get("id"),
                "case_id": item.get("case_id"),
                "subjective_experience": item.get("subjective_experience", ""),
                "review_criteria": item.get("review_criteria", ""),
            }
            for item in matched_experiences
        ],
    }
    recommendations = [rule.get("recommendation") for rule in matched_rules if rule.get("recommendation")]
    if recommendations:
        review["memory_recommendations"] = recommendations
    return review


def add_feedback(case_id: str, label: str, note: str, score_adjustment: float | None = None) -> dict[str, Any]:
    memory = load_memory()
    item = {
        "id": stable_id("feedback", case_id, label, note[:40]),
        "created_at": now_iso(),
        "case_id": case_id,
        "label": label,
        "note": note,
    }
    if score_adjustment is not None:
        item["score_adjustment"] = score_adjustment
    memory["feedback"].append(item)
    save_memory(memory)
    return item


def add_experience(case_id: str, subjective_experience: str, review_criteria: str = "", source: str = "manual") -> dict[str, Any]:
    memory = load_memory()
    item = {
        "id": stable_id("exp", case_id, subjective_experience[:60], review_criteria[:40]),
        "created_at": now_iso(),
        "case_id": case_id,
        "raw_tiff_path": "",
        "subjective_experience": subjective_experience,
        "review_criteria": review_criteria,
        "status": "active_context",
        "source": source,
    }
    existing = {entry.get("id") for entry in memory.get("experiences", [])}
    if item["id"] not in existing:
        memory["experiences"].append(item)
        save_memory(memory)
    return item


def add_rule(
    label: str,
    keywords: list[str],
    flags: list[str],
    assumptions: list[str],
    score_adjustment: float,
    recommendation: str,
) -> dict[str, Any]:
    memory = load_memory()
    rule = {
        "id": stable_id("rule", label),
        "created_at": now_iso(),
        "active": True,
        "source": "manual",
        "label": label,
        "keywords": keywords,
        "applies_to_flags": flags,
        "applies_to_assumptions": assumptions,
        "score_adjustment": score_adjustment,
        "recommendation": recommendation,
    }
    memory["learned_rules"].append(rule)
    save_memory(memory)
    return rule


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect and update Franklin local memory.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("show", help="Print memory summary.")

    feedback = sub.add_parser("feedback", help="Record human feedback for a case.")
    feedback.add_argument("--case-id", required=True)
    feedback.add_argument("--label", required=True, choices=["good", "bad", "uncertain"])
    feedback.add_argument("--note", required=True)
    feedback.add_argument("--score-adjustment", type=float)

    experience = sub.add_parser("experience", help="Record reusable Franklin experience for a case.")
    experience.add_argument("--case-id", required=True)
    experience.add_argument("--note", required=True)
    experience.add_argument("--criteria", default="")

    rule = sub.add_parser("add-rule", help="Add a structured scoring rule.")
    rule.add_argument("--label", required=True)
    rule.add_argument("--keyword", action="append", default=[])
    rule.add_argument("--flag", action="append", default=[])
    rule.add_argument("--assumption", action="append", default=[])
    rule.add_argument("--score-adjustment", type=float, required=True)
    rule.add_argument("--recommendation", required=True)

    args = parser.parse_args()
    if args.command == "show":
        memory = load_memory()
        print(
            json.dumps(
                {
                    "memory_path": str(MEMORY_PATH),
                    "experiences": len(memory.get("experiences", [])),
                    "learned_rules": len(memory.get("learned_rules", [])),
                    "feedback": len(memory.get("feedback", [])),
                    "pending_rule_proposals": len(memory.get("pending_rule_proposals", [])),
                    "updated_at": memory.get("updated_at"),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    elif args.command == "feedback":
        item = add_feedback(args.case_id, args.label, args.note, args.score_adjustment)
        print(json.dumps(item, indent=2, ensure_ascii=False))
    elif args.command == "experience":
        item = add_experience(args.case_id, args.note, args.criteria)
        print(json.dumps(item, indent=2, ensure_ascii=False))
    elif args.command == "add-rule":
        item = add_rule(
            label=args.label,
            keywords=args.keyword,
            flags=args.flag,
            assumptions=args.assumption,
            score_adjustment=args.score_adjustment,
            recommendation=args.recommendation,
        )
        print(json.dumps(item, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
