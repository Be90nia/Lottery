# LOT-055 checkpoint integrity note

The exact-subset rolling-origin manifest and checkpoint headers bind to the same evaluator source commit. Checkpoint gradient norms must be finite and non-negative.

The checkpoint record hash covers the complete target record. Resume validates the frozen snapshot, target order, training cutoff/count, all four model scores, fit statuses, and the legal uniform NLL constant before accepting a previously written target.
