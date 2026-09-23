# Sources

This baseline is a local PyTorch implementation of the standard TCN design:
causal dilated convolutions, residual temporal blocks, and a final prediction
head.

It does not vendor or copy source files from the upstream repository. The
architecture reference is:

- Official repository: https://github.com/locuslab/TCN
- Paper: https://arxiv.org/abs/1803.01271
- Upstream repository license: MIT

The Gaussian probabilistic head and the industrial dataset adaptation are
project-specific additions for `/home/work/new_work`.
