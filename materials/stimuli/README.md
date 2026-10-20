# Stimuli

Saved parameters, Houdini scenes and textures for the experiment videos.
The videos themselves are in the adjacent `experiments/` folders.

- `parameters/`: 441 single and 78 ensemble files for Experiment 1; 236 files for Experiment 2.
- `scenes/`: single-marble and ensemble Houdini Apprentice scenes.
- `assets/`: environment map and textures.
- `render.py`: render saved parameters.
- `generate_parameters.py`: generate new parameters with an explicit seed.
- `mass_design.py`: ensemble mass calculations.

From this folder:

```bash
python render.py list experiment1-single --limit 3
python render.py render experiment2-normal mass_80/m80_s0_v7 --dry-run --video
python mass_design.py check
```

Rendering requires Houdini Apprentice with an activated license and `hython`
on PATH; video encoding requires FFmpeg. Existing videos can be used without
Houdini. New renders are saved under `generated/`.

To generate a new stimulus set:

```bash
python generate_parameters.py experiment2 --name example --seed 42 --mass 8 --variations 3
```

Generated parameter sets include their seed and settings.

The scene mass parameter is density; equal marble geometry makes density ratios
mass ratios. Ensemble masses are defined in log space around their geometric mean.

The environment map is [Kiara 1 Dawn](https://polyhaven.com/a/kiara_1_dawn) from
Poly Haven. Art Deco and nylon textures are from [3DTextures](https://3dtextures.me/about/).
These assets are CC0. Houdini scenes use the noncommercial Apprentice `.hipnc` format.
