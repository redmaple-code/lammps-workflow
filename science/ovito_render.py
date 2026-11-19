"""Render an actual atomic cross-section using the versioned legacy OVITO adapter."""
from pathlib import Path
import argparse
import sys
import json
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
ADAPTER=Path(__file__).parent
if not (ADAPTER/'ovito_adapter.py').exists():
    ADAPTER=ROOT/'packages/presentation'
sys.path.insert(0,str(ADAPTER))
from ovito_adapter import render_section
from ovito.io import import_file
from ovito.modifiers import ExpressionSelectionModifier, DeleteSelectedModifier
import ovito


def render(directory):
    directory=Path(directory)
    structure=json.loads((directory/'structure-report.json').read_text())
    center=structure['boxAngstrom'][1]/2
    pipeline=import_file(str(directory/'final.lammpstrj'))
    original=pipeline.compute()
    original_count=original.particles.count
    pipeline.modifiers.append(ExpressionSelectionModifier(expression=f'abs(Position.Y-{center})>5.0'))
    pipeline.modifiers.append(DeleteSelectedModifier())
    data=pipeline.compute()
    if data.particles.count==0:
        raise ValueError('Slice removed the complete research object')
    pipeline.source.data.particles.vis.radius=0.72
    meta=render_section(pipeline,directory/'figures/grinding-atoms-ovito.png')
    meta.update(tool='OVITO',version=ovito.version_string,source='final.lammpstrj',
                timestep=int(original.attributes['Timestep']),originalParticles=original_count,
                selection={'kind':'central-y-slab','centerAngstrom':center,'halfWidthAngstrom':5},
                coloring='particle type',elements={'1':'Fe','2':'Ni','3':'Cr','4':'Co','5':'Cu'},
                template='packages/presentation/ovito_adapter.py',
                note='Spherical analytical abrasive is a force field and has no particle representation in this image')
    (directory/'render-meta.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    print(json.dumps(meta))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',required=True)
    render(p.parse_args().directory)
