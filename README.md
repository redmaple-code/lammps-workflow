# LAMMPS simulation workflow

Snapshot of the Pi-lammps LAMMPS grinding domain workflow, role definitions, checks, templates, reference materials and scientific scripts. The domain manifest is a draft (v0.1.0); its local LAMMPS tool binding is unverified and quantitative production prediction is excluded.

- `domains/lammps/manifest.json`: workflow stages and domain resources.
- `science/` and `grinding-workflow.js`: implementation excerpts. These depend on the Pi-lammps host and are not a standalone application.
- `legacy-workflow-templates/`: historical workflow templates and knowledge capsule. The original skill entrypoints and validation scripts are absent from this snapshot; its README and installation instructions describe the original package and cannot be followed as-is.

Scientific and numerical validation remain necessary for any new case.
