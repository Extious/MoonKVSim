# Main manuscript consolidation

The selected eight-page manuscript is now `paper/`, built with `experiments/scripts/paper/build_paper.sh`. The prior full manuscript was moved intact to `Archived/main-before-consolidation-20260923T061913Z/paper/`.

All active TeX labels, references, comments, figure filenames and build/generation entrypoints use neutral names. The main source contains Background, Motivation, System Design, and references; the four Design components remain unchanged.

Validation: all 27 checks in `checks.json` pass. The renamed figure inputs and previews are byte-identical; regenerated editable diagram geometry is identical. The compiled PDF still has eight pages with identical extracted text and rendered pixels on every page. Pages 3 and 4 were rendered at 1.5x and visually reviewed. No unresolved/duplicate references or overfull boxes remain in the compiled manuscript. Commented and disabled supplied alternatives are excluded from reference checking.

This is a naming and manuscript-location change, with no changes to scientific claims, data, diagram geometry, or implementation. Historical packages retain their original names for provenance.
