"""Read-only table32 evidence reconstruction; never starts external processes."""
from __future__ import annotations

from pathlib import Path
import math

import table32_store as st


def verify_attempts(root,manifest):
    charged=0
    for index,path in enumerate(sorted((Path(root)/"attempts").glob("[0-9]*"))):
        st.require(path.name==f"{index:04d}","attempt sequence differs")
        provenance=st.read(path/"provenance.json")
        st.require(provenance["manifest_digest"]==st.digest(manifest)
            and provenance["execution_commit"]==manifest["producer_commit"]
            and provenance["effective_settings"]==manifest["settings"]
            and provenance["resource_limits"]==manifest["limits"]
            and provenance["prior_charged_seconds"]==charged,"attempt settings/chain differs")
        budget=st.read(path/"budget.json")["charged_seconds"]
        st.require(type(budget) in (int,float) and math.isfinite(budget) and budget>=0,
                   "attempt budget invalid")
        charged+=budget
        completion=path/"completion.json"
        if completion.exists():
            saved=st.read(completion)
            st.require(saved==st.seal(saved) and saved["charged_seconds"]==budget
                       and all(saved.get(k)==v for k,v in provenance.items()),"attempt completion differs")
        failure=path/"failure.json"
        if failure.exists():
            saved=st.read(failure)
            st.require(saved==st.seal(saved) and all(saved.get(k)==v for k,v in provenance.items()),
                       "attempt failure provenance differs")
            for relative,sha in saved["raw_log_digests"].items():
                target=(path/relative).resolve()
                st.require(path.resolve() in target.parents and st.pin(target)["sha256"]==sha,
                           "failure raw log changed")
    st.require(charged<=manifest["limits"]["wall_seconds"],"cumulative execution budget exceeded")
    return charged


def verify(root, *, manifest=None, snapshot=None):
    from table32 import Driver, MissingUnit, cycle, load
    root = Path(root)
    if manifest is None:
        manifest, snapshot = load(root)
    verify_attempts(root,manifest)
    # Extension permission is evidence, not an outcome inferred from20 points.
    extension = False
    scan = st.Journal(root,manifest)
    for entry in scan.entries():
        if entry["phase"] == "explicit-match200":
            extension = True
    driver = Driver(root,manifest,execute=False)
    try:
        report = cycle(driver,snapshot,extend=extension)
        driver.finish()
    except MissingUnit as missing:
        st.require(not (root/"report.json").exists(),"incomplete run has a final report")
        return {"status":"incomplete","outcome":"saved-prefix-verified",
                "completed_units":driver.journal.cursor,
                "prefix_digest":driver.journal.previous,
                "missing_unit":missing.unit,"resume_phase":missing.phase,
                "adopted_model_replaced":False,"acceptance_0018":False}
    target = "screening-report.json" if report["outcome"]=="awaiting-explicit-continue" else "report.json"
    st.require((root/target).is_file() and st.read(root/target)==report,
               "published table32 report differs from offline reconstruction")
    receipt=root/("screening-verification.receipt.json" if target=="screening-report.json"
                   else "offline-verification.receipt.json")
    if receipt.exists():
        st.require(st.read(receipt)==st.seal({"report_digest":st.digest(report),
            "manifest_digest":st.digest(manifest),"prefix_digest":driver.journal.previous}),
            "offline verification receipt differs")
    return report
