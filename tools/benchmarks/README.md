# OpenFusion benchmarks

Benchmark tooling will live here with representative, redistributable test
documents and machine-readable results. No performance claim is accepted
without the exact revision, build type, dependency lock, host, renderer, input
model, warm-up policy, repetitions, and raw measurements.

The initial suites will cover:

- cold and warm startup;
- FCStd and imported STEP load time;
- document recomputation, including a 100-feature part;
- dense-sketch solver latency;
- viewport frame rate and selection latency;
- multi-component assembly interaction; and
- peak resident memory.

Benchmarks are not yet implemented. Until an untouched FreeCAD 1.1.3 baseline
has been recorded, this directory must not contain fabricated target numbers or
hand-authored result files.
