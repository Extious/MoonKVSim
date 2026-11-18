"""Read-only external-review readiness gate. Never publishes, reviews, builds, or runs DES."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
BASE = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924"
PAPER = ROOT / "benchmark/AegisKV/paper"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def canonical_sha(value):
    raw = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def active_graphics(text):
    # This manuscript uses literal includegraphics paths, not macro-generated paths.
    text = re.sub(r"(?<!\\)%[^\n]*", "", text)
    return re.findall(r"\\includegraphics(?:\[[^]]*\])?\{([^{}]+)\}", text)


class Gate:
    def __init__(self, config):
        self.config = config
        self.checks = []
        self.hashes = {}
        self.notices = []

    def sha(self, path):
        path = Path(path).resolve()
        value = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                value.update(chunk)
        digest = value.hexdigest()
        self.remember(path, digest)
        return digest

    def remember(self, path, digest):
        path = Path(path).resolve()
        old = self.hashes.get(str(path))
        require(old is None or old == digest, f"input changed during gate: {path}")
        self.hashes[str(path)] = digest

    def read(self, path):
        raw = Path(path).read_bytes()
        self.remember(path, hashlib.sha256(raw).hexdigest())
        return json.loads(raw)

    def stable_inputs(self):
        for path, digest in list(self.hashes.items()):
            self.match(path, digest)
        return dict(rehashed_inputs=len(self.hashes))

    def match(self, path, expected):
        require(self.sha(path) == expected, f"SHA-256 mismatch: {path}")

    def closure(self, base, mapping):
        require(bool(mapping), f"empty seal: {base}")
        for relative, digest in mapping.items():
            self.match(
                Path(base) / relative, digest["sha256"] if isinstance(digest, dict) else digest
            )

    def group(self, name, function):
        try:
            details = function()
            self.checks.append(dict(name=name, status="PASS", details=details))
        except (OSError, ValueError, KeyError, TypeError, AssertionError, StopIteration) as error:
            self.checks.append(dict(name=name, status="NOT_READY", reason=str(error)))

    def identity(self):
        self.closure(ROOT, self.config["pinned_sha256"])
        return dict(pinned_files=len(self.config["pinned_sha256"]))

    def primary(self):
        out = BASE / "walltime-primary-v3"
        state = self.read(out / "STATUS.json")
        require(
            state.get("complete") is True and state.get("completed_runs") == 180,
            f"primary incomplete: {state.get('completed_runs')}/180",
        )
        plan, manifest, priors = [
            self.read(out / n) for n in ("PLAN.json", "MANIFEST.json", "PRIORS.json")
        ]
        require(len(plan["jobs"]) == 180, "primary plan is not 180 conditions")
        self.closure(out, self.read(out / "PROTOCOL_SEAL.json")["sha256"])
        self.closure(out / "source_snapshot", manifest["source_sha256"])
        self.closure(out, manifest["predictor_sha256"])
        self.closure(out, manifest["control_sha256"])
        audit = self.read(out / "AUDIT.json")
        require(
            audit["status"] == "PASS" and audit["verified_runs"] == 180, "numeric audit not PASS180"
        )
        for job in plan["jobs"]:
            run = out / "runs" / job["id"]
            marker = self.read(run / "COMPLETE.json")
            require(marker["id"] == job["id"] and marker["complete"] is True, "wrong run marker")
            require(marker["job_sha256"] == canonical_sha(job), "job identity mismatch")
            self.match(out / "PROTOCOL_SEAL.json", marker["protocol_seal_sha256"])
            self.match(out / "PRIORS.json", marker["priors_sha256"])
            self.match(out / job["predictor"], marker["predictor_sha256"])
            self.closure(run, marker["artifacts_sha256"])
            summary = self.read(run / "summary.json")
            require(
                summary["complete"]
                and summary["output_tokens_exact"]
                and summary["terminal_allocations_zero"]
                and summary["oracle_reservation_count"] == 0,
                "primary completion/output/resource invariant missing",
            )
            config = self.read(run / "config.json")
            require(config == job["config"], "run config differs from plan")
            require(
                config["slack_guard_ns"] == priors[job["model"]]["slack_guard_ns"], "wrong guard"
            )
        endpoint = self.read(out / "endpoints/PROVENANCE.json")
        require(
            endpoint["status"] == "PASS"
            and endpoint["source_summary_count"] == 180
            and endpoint["fault_rows"] == 150,
            "endpoint counts/status incomplete",
        )
        self.closure(out, endpoint["source_sha256"])
        self.closure(out / "endpoints", endpoint["output_sha256"])
        deployment = self.read(out / "endpoints/WALLTIME_MODEL_PROVENANCE.json")
        require(
            deployment["predictor_sha256"] == manifest["predictor_sha256"], "wrong endpoint models"
        )
        for name, field in (
            ("PLAN.json", "plan_sha256"),
            ("PROTOCOL_SEAL.json", "protocol_seal_sha256"),
            ("endpoints/PROVENANCE.json", "endpoint_provenance_sha256"),
        ):
            self.match(out / name, deployment[field])
        post = self.read(out / "PAPER_POSTPROCESS_COMPLETE.json")
        require(
            post["status"] == "NUMERIC_COMPLETE_VISUAL_REVIEW_PENDING",
            "unrecognized numeric postprocess status; do not relabel it scientific PASS",
        )
        self.closure(out, self.read(out / "PAPER_POSTPROCESS_SEAL.json")["sha256"])
        self.closure(out, post["output_sha256"])
        plot = self.read(out / "figures/PROVENANCE.json")
        self.match(out / "endpoints/per-identity.csv", plot["data_sha256"])
        self.match(out / "endpoints/PROVENANCE.json", plot["input_provenance_sha256"])
        self.match(
            out / "postprocess_source_snapshot/plot_primary_endpoints.py", plot["plot_sha256"]
        )
        self.match(
            out / "postprocess_source_snapshot/plot_profile_campaign.py",
            plot["style_source_sha256"],
        )
        self.closure(out / "figures", plot["output_sha256"])
        for name, field in (
            ("PAPER_POSTPROCESS_SEAL.json", "postprocess_seal_sha256"),
            ("AUDIT.json", "audit_sha256"),
            ("endpoints/PROVENANCE.json", "endpoint_sha256"),
            ("MANIFEST.json", "manifest_sha256"),
            ("PLAN.json", "plan_sha256"),
            ("PRIORS.json", "priors_sha256"),
            ("PROTOCOL_SEAL.json", "protocol_seal_sha256"),
        ):
            self.match(out / name, post[field])
        require(
            post["predictor_sha256"] == manifest["predictor_sha256"], "wrong postprocess models"
        )
        require(
            post["guard_ns"] == {m: p["slack_guard_ns"] for m, p in priors.items()},
            "wrong postprocess guards",
        )
        for name in (
            "HELDOUT_INDEPENDENT_AUDIT.json",
            "paper-summary/FALLBACK_CONTROL_WINDOWS.json",
            "paper-summary/V2_V3_COMPARISON.json",
        ):
            require(self.read(out / name)["status"] == "PASS", f"missing diagnostic: {name}")
        # Never edit postprocess completion/output hashes to mark a new visual review.
        visual = self.read(ROOT / self.config["primary_visual_review"])
        require(
            visual["status"] == "PASS" and visual["color_and_grayscale_actually_inspected"] is True,
            "primary actual-size visual review pending",
        )
        self.match(out / "figures/primary-target-wct.pdf", visual["pdf_sha256"])
        self.match(out / "PAPER_POSTPROCESS_COMPLETE.json", visual["postprocess_complete_sha256"])
        self.closure(out / "figures", visual["render_sha256"])
        require(
            {"final-size-color.png", "final-size-gray.png"} <= set(visual["render_sha256"]),
            "primary visual review lacks both actual renders",
        )
        return dict(conditions=180, fault_endpoints=150, postprocess_status=post["status"])

    def execution_amendment(self):
        out = BASE / "walltime-primary-v3"
        directory = out / "execution-amendment-16workers"
        amendment, stopped = [
            self.read(directory / name) for name in ("AMENDMENT.json", "STOPPED_STATE.json")
        ]
        self.match(directory / "STOPPED_STATE.json", amendment["stopped_state_sha256"])
        self.match(out / "PROTOCOL_SEAL.json", amendment["original_protocol_seal_sha256"])
        self.closure(out, stopped["completed_artifact_sha256"])
        complete = self.read(directory / "EXECUTION_COMPLETE.json")
        require(
            complete["status"] == "PASS"
            and complete["completed_runs"] == 180
            and complete["all_prior_completed_artifacts_unchanged"]
            and complete["original_protocol_and_sources_unchanged"],
            "execution amendment not complete",
        )
        validation = self.read(directory / "PARALLELISM_VALIDATION.json")
        require(
            validation["status"] == "PASS" and validation["case"] == amendment["validation_job"],
            "wrong parallel validation identity",
        )
        for name, row in validation["artifacts"].items():
            require(row["equal"] is True, "parallel validation differs")
            original = out / "runs" / amendment["validation_job"] / name
            replay = out / "validation/parallel16" / name
            self.sha(original)
            self.sha(replay)
            a, b = original.read_bytes(), replay.read_bytes()
            if name.endswith(".gz"):
                a, b = gzip.decompress(a), gzip.decompress(b)
            require(
                a == b and hashlib.sha256(a).hexdigest() == row["content_sha256"],
                f"parallel validation bytes changed: {name}",
            )
        self.notices.append(
            "16-worker execution-only amendment retained; "
            "host wall_seconds are not compared across execution modes."
        )
        return dict(workers=16, validation_extra_samples=validation["extra_experimental_samples"])

    def auxiliary(self):
        low = BASE / "low-dma-postreview-v1"
        seal = self.read(low / "PACKAGE_COMPLETE.json")
        require(
            seal["status"] == "COMPLETE" and seal["new_conditions"] == 24, "lowDMA seal incomplete"
        )
        self.closure(low, seal["sha256"])
        self.closure(low / "source_snapshot", self.read(low / "MANIFEST.json")["source_sha256"])
        audit = self.read(low / "AUDIT.json")
        require(audit["complete"] and audit["verified_runs"] == 24, "lowDMA audit incomplete")
        require(
            self.read(low / "FLOW_AUDIT.json")["status"] == "PASS", "lowDMA flow audit incomplete"
        )
        jobs = self.read(low / "PLAN.json")["jobs"]
        require(len(jobs) == 24, "wrong lowDMA plan count")
        for job in jobs:
            run = low / "runs" / job["id"]
            marker = self.read(run / "COMPLETE.json")
            require(marker["job_sha256"] == canonical_sha(job), "lowDMA job mismatch")
            self.closure(run, marker["artifact_sha256"])
        native = BASE / "native-transfer-postreview-v2"
        seal = self.read(native / "DELIVERY.json")
        require(
            seal["status"] == "PASS" and seal["numerical_matrix_complete"], "native seal incomplete"
        )
        self.closure(native, seal["sha256"])
        audit = self.read(native / "INDEPENDENT_AUDIT.json")
        require(audit["status"] == "PASS" and audit["cases"] == 864, "native audit not864")
        self.sha(native / "document-results.csv")
        with (native / "document-results.csv").open() as stream:
            require(len(list(csv.DictReader(stream))) == 864, "native table not864 rows")
        quota = BASE / "quota-pressure-postreview-v1"
        seal = self.read(quota / "FINAL_AUDIT.json")
        require(seal["status"] == "COMPLETE" and seal["formal_runs"] == 72, "quota seal incomplete")
        self.closure(quota, seal["artifact_sha256"])
        audit = self.read(quota / "AUDIT.json")
        require(audit["status"] == "PASS" and audit["verified_runs"] == 72, "quota audit not72")
        return dict(
            low_dma_new_conditions=24,
            native_method_conditions=864,
            quota_conditions=72,
            independent_repeat_claim=False,
        )

    def preservation(self):
        record = self.read(BASE / "PRESERVED_MANUSCRIPT.json")
        for relative, expected in record["files"].items():
            path = ROOT / relative
            if path == PAPER / "main.tex":
                self.sha(path)
                text = path.read_text()
                require(
                    text.count("\\input{evaluation}\n") == 1, "unexpected Evaluation input count"
                )
                text = text.replace("\\input{evaluation}\n", "").replace(
                    "\\bibliography{references,evaluation-references}", "\\bibliography{references}"
                )
                require(
                    hashlib.sha256(text.encode()).hexdigest() == expected,
                    "main.tex outside allowed changes",
                )
            else:
                self.match(path, expected)
        require(
            self.config["front_matter_edit_permission"] == "pending",
            "permission status changed: explicitly review config",
        )
        self.notices.append(
            "Permission for seven proposed preceding-text edits is still pending. "
            "Preceding text is preserved; readiness only permits external review, "
            "not these edits or publication."
        )
        return dict(preserved_files=len(record["files"]), pending_permission=True)

    def figures(self):
        self.sha(PAPER / "evaluation.tex")
        refs = active_graphics((PAPER / "evaluation.tex").read_text())
        expected = self.config["evaluation_figures"]
        require(
            len(refs) == 4 and len(set(refs)) == 4,
            "expected exactly four literal Evaluation figures",
        )
        require(set(refs) == set(expected), f"actual Evaluation figure set differs: {refs}")
        for ref, origin in expected.items():
            require(
                self.sha(PAPER / ref) == self.sha(ROOT / origin),
                f"figure campaign binding differs: {ref}",
            )
        # Re-rendered sensitivity figure is bound to its original data, not v3 WCT.
        for directory in (
            BASE / "reviews/resource-markers-postreview",
            BASE / "reviews/native-transfer-figure-v1",
            BASE / "reviews/native-transfer-paper-summary-v1",
        ):
            seal = self.read(directory / "SEAL.json")
            require(seal["status"] == "PASS", f"figure seal not PASS: {directory}")
            self.closure(directory, seal["files"])
        native_seal = self.read(BASE / "reviews/native-transfer-figure-v1/SEAL.json")
        self.match(
            BASE / "native-transfer-postreview-v2/DELIVERY.json",
            native_seal["source_native_delivery_sha256"],
        )
        self.match(
            BASE / "reviews/native-transfer-paper-summary-v1/SEAL.json",
            native_seal["source_summary_seal_sha256"],
        )
        structural = BASE / "structural-campaign-v2-main"
        metadata = self.read(structural / "figures/EXPORT_METADATA.json")
        review = self.read(structural / "figures/FIGURE_REVIEW.json")
        require(review["passed"] is True, "structural figure review not PASS")
        self.closure(structural, metadata["inputs"])
        selected = next(x for x in metadata["exports"] if x["name"] == "structural-target-wct")
        self.match(structural / "figures/structural-target-wct.pdf", selected["pdf_sha256"])
        self.match(structural / "figures/EXPORT_METADATA.json", review["export_metadata_sha256"])
        self.notices.append(
            "Only four actually referenced Evaluation figures count; "
            "an unreferenced historical eval-native-topk.pdf may remain on disk."
        )
        return dict(actual_references=refs, count=4)

    def paper_reviews(self):
        export_path = ROOT / self.config["paper_export_review"]
        visual_path = ROOT / self.config["paper_visual_review"]
        export, visual = self.read(export_path), self.read(visual_path)
        require(visual["status"] == "PASS", "whole-paper visual review not PASS")
        for record in (export, visual):
            self.match(PAPER / "main.pdf", record["manuscript_sha256"])
            self.match(PAPER / "evaluation.tex", record["tex_sha256"])
        self.match(export_path, visual["export_review_sha256"])
        require(
            visual.get("scientific_or_publication_approval") is False,
            "visual record must not imply scientific/publication approval",
        )
        self.closure(visual_path.parent, visual["render_sha256"])
        first, last = export["evaluation_page_range"]
        require(
            type(first) is int and type(last) is int and 1 <= first <= last <= export["page_count"],
            "invalid or empty final Evaluation page range",
        )
        evaluation_pages = set(range(first, last + 1))
        require(
            evaluation_pages <= set(visual["color_pages_checked"])
            and evaluation_pages <= set(visual["grayscale_pages_checked"]),
            "whole-paper color/grayscale inspection must cover every final Evaluation page",
        )
        for page in evaluation_pages:
            for mode in ("color", "gray"):
                require(
                    f"page-{page}-{mode}.png" in visual["render_sha256"],
                    f"unbound final Evaluation render: page {page} {mode}",
                )
        for field, record in (("evaluation_figures", export), ("figures", visual)):
            rows = {Path(r["path"]).name: r for r in record[field]}
            for relative in self.config["evaluation_figures"]:
                name = Path(relative).name
                require(name in rows, f"review missing actually referenced figure {name}")
                self.match(PAPER / relative, rows[name]["sha256"])
        for path in PAPER.iterdir():
            if path.suffix in {".tex", ".bib", ".cls", ".sty", ".bst"}:
                self.sha(path)
        full_tex = (PAPER / "evaluation.tex").read_text()
        require(
            not re.search(r"\bTODO\b|NOT_V3_RESULTS|PLACEHOLDER", full_tex),
            "draft placeholder remains, including source comments",
        )
        return dict(
            manuscript_sha256=export["manuscript_sha256"],
            evaluation_sha256=export["tex_sha256"],
            page_count=export["page_count"],
            external_review_started=False,
        )

    def check(self):
        for name, operation in (
            ("pinned_identity", self.identity),
            ("primary180", self.primary),
            ("execution_amendment", self.execution_amendment),
            ("auxiliary_seals", self.auxiliary),
            ("preceding_text_preservation", self.preservation),
            ("four_evaluation_figures", self.figures),
            ("matching_paper_export_and_visual", self.paper_reviews),
            ("all_inputs_stable_at_end", self.stable_inputs),
        ):
            self.group(name, operation)
        ready = all(c["status"] == "PASS" for c in self.checks)
        return dict(
            status="READY_FOR_EXTERNAL_REVIEW" if ready else "NOT_READY",
            checked_utc=datetime.now(UTC).isoformat(),
            checks=self.checks,
            notices=self.notices,
            source_sha256=self.hashes,
            front_matter_edit_permission="pending",
            external_review_started=False,
            publication_performed=False,
            scientific_or_publication_approval=False,
            goal_complete=False,
            boundary=(
                "Hash/completeness/visual-review evidence gate only; "
                "the next external review can still reject the paper."
            ),
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("CONFIG.json"))
    parser.add_argument("--output", type=Path, required=True, help="A new, nonexistent result file")
    args = parser.parse_args()
    require(not args.output.exists(), "Do not overwrite a previous gate result")
    config = json.loads(args.config.read_bytes())
    gate = Gate(config)
    gate.sha(Path(__file__))
    gate.sha(args.config)
    preparation = gate.read(Path(__file__).with_name("PREPARATION_SEAL.json"))
    gate.match(Path(__file__), preparation["sha256"]["check.py"])
    gate.match(args.config, preparation["sha256"]["CONFIG.json"])
    result = gate.check()
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(result["status"])
    raise SystemExit(0 if result["status"] == "READY_FOR_EXTERNAL_REVIEW" else 2)


if __name__ == "__main__":
    main()
