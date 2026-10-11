# HAT-inspired local descriptor research (NOT part of Free)

This is an independent offline implementation of publicly documented FAST,
SIFT, nearest-neighbor descriptor ideas for optional style comparison research.
Original HAT source is not copied; its checked-in AGPL-3.0 license conflicts
with its About-page CC BY-NC statement, so code reuse requires a rights decision.

The pure functions in descriptors.py compute limited local keypoints and
descriptor-match counts. No population baseline, author match probability,
semantic interpretation or forensic identity claim is implied.

Use only explicit consent/rights-cleared images in a protected local environment.
Keep participant data and generated descriptor arrays outside this Git repository,
public Actions artifacts and the Free server. Split repeated captures by writer,
not individual photo, and evaluate multiple sessions, quality conditions and
cross-writer negative pairs. No user-facing product PR is authorized by this
research baseline.

The zero/one-reference-descriptor case is handled without division by zero;
orientation differences use circular distance; descriptor and image size caps
are enforced. Actual comparative validity remains an open empirical gate.

A protected offline prototype ranking runner is available as `python -m evaluation.style_similarity.evaluate --manifest /approved/manifest.json --image-root /approved/images --allow-authorized-real`. It refuses reused capture groups, bounds the experiment, returns only aggregate ranking metrics and never emits identity labels. `top1_fraction` is held-out experimental ranking accuracy on the explicitly declared candidate set, never an identity-match probability. Splitting development/holdout by writer is an external protocol obligation and is not proved by a single manifest.
